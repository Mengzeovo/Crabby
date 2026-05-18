"""Context meter — estimate token usage before each LLM call.

Provides a token estimator and structured breakdown of context composition
(system prompt, tool schema, messages by role).

Token estimation strategy (in priority order):
  1. tiktoken cl100k_base — covers OpenAI, DeepSeek, Qwen, Kimi, MiniMax, Zhipu
  2. Fallback heuristic with content-type-aware ratios:
       - CJK text: 1.7 chars/token
       - JSON/schema: 2.0 chars/token
       - Code blocks:  2.5 chars/token
       - Tool results:  2.8 chars/token
       - Plain text:    4.0 chars/token
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import tiktoken


logger = logging.getLogger(__name__)

# ── Tokenizer cache ──────────────────────────────────────────────────────────

_tiktoken_enc: "tiktoken.Encoding | None" = None


def _get_tiktoken() -> "tiktoken.Encoding":
    global _tiktoken_enc
    if _tiktoken_enc is None:
        import tiktoken as _tiktoken

        _tiktoken_enc = _tiktoken.get_encoding("cl100k_base")
    return _tiktoken_enc


# ── CJK detection ────────────────────────────────────────────────────────────

_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]"
)

# Heuristic chars-per-token ratios, tuned for the content types that differ most
# from the "4 chars ≈ 1 token" baseline.
_HEURISTIC_RATIOS: dict[str, float] = {
    "json_schema": 2.0,
    "code": 2.5,
    "tool_result": 2.8,
    "plain": 4.0,
}


def _cjk_heuristic(text: str, ratio: float) -> int:
    cjk_chars = len(_CJK_RE.findall(text))
    non_cjk = len(text) - cjk_chars
    return max(1, int(cjk_chars / 1.7 + non_cjk / ratio))


def estimate_tokens(text: str, *, content_type: str = "plain") -> int:
    """Estimate token count for a string.

    Args:
        text: The string to estimate.
        content_type: One of "plain" | "json_schema" | "code" | "tool_result".
                      Affects the heuristic fallback ratio when tiktoken is unavailable.
                      Defaults to "plain".
    """
    if not text:
        return 0

    ratio = _HEURISTIC_RATIOS.get(content_type, 4.0)

    try:
        enc = _get_tiktoken()
        # tiktoken encodes all text equivalently regardless of "content_type"
        # — the type only affects the heuristic fallback path.
        return len(enc.encode(text))
    except (OSError, ValueError):
        # tiktoken raises OSError on missing vocab file and ValueError on
        # malformed input (e.g. surrogate characters that encode() can't handle).
        # All other exceptions are unexpected and should propagate.
        pass

    return _cjk_heuristic(text, ratio)


def _content_to_text(content: Any) -> str:
    """Flatten message content (str or list of blocks) to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    source = block.get("source", {})
                    parts.append(f"[image:{source.get('media_type', 'image')}]")
                elif block.get("type") == "tool_use":
                    parts.append(json.dumps(block.get("input", {}), ensure_ascii=False))
                elif block.get("type") == "tool_result":
                    parts.append(str(block.get("content", "")))
                else:
                    parts.append(json.dumps(block, ensure_ascii=False))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


def _is_tool_result_msg(msg: dict[str, Any]) -> bool:
    content = msg.get("content", "")
    if isinstance(content, list):
        return any(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
    return False


# ── Context breakdown ─────────────────────────────────────────────────────────

# 200k token — matches the LLMProviderPreset default; used as the fallback
# context_limit in to_dict() when the caller doesn't provide one.
CONTEXT_LIMIT = 200_000


@dataclass
class ContextBreakdown:
    """Structured breakdown of context token usage."""

    system_tokens: int = 0
    schema_tokens: int = 0
    user_tokens: int = 0
    assistant_tokens: int = 0
    tool_result_tokens: int = 0
    message_count: int = 0
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_result_count: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.system_tokens
            + self.schema_tokens
            + self.user_tokens
            + self.assistant_tokens
            + self.tool_result_tokens
        )

    def to_dict(self, context_limit: int = CONTEXT_LIMIT) -> dict[str, Any]:
        usage_percent = round(self.total_tokens / context_limit * 100, 1) if context_limit else 0.0
        return {
            "total_tokens": self.total_tokens,
            "system_tokens": self.system_tokens,
            "schema_tokens": self.schema_tokens,
            "user_tokens": self.user_tokens,
            "assistant_tokens": self.assistant_tokens,
            "tool_result_tokens": self.tool_result_tokens,
            "message_count": self.message_count,
            "user_message_count": self.user_message_count,
            "assistant_message_count": self.assistant_message_count,
            "tool_result_count": self.tool_result_count,
            "context_limit": context_limit,
            "usage_percent": usage_percent,
        }

    def to_log_line(self, context_limit: int = CONTEXT_LIMIT) -> str:
        return (
            f"[context] system={self.system_tokens} schema={self.schema_tokens} "
            f"user={self.user_tokens} assistant={self.assistant_tokens} "
            f"tool_result={self.tool_result_tokens} "
            f"total={self.total_tokens}/{context_limit} "
            f"({self.total_tokens / context_limit * 100:.1f}%) "
            f"msgs={self.message_count}"
        )


def measure_context(
    system_prompt: str,
    tools_schema: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]],
) -> ContextBreakdown:
    """Measure token usage of the full context that will be sent to the LLM."""
    breakdown = ContextBreakdown()

    breakdown.system_tokens = estimate_tokens(system_prompt)

    if tools_schema:
        schema_text = json.dumps(tools_schema, ensure_ascii=False)
        breakdown.schema_tokens = estimate_tokens(schema_text, content_type="json_schema")

    breakdown.message_count = len(messages)
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        content_text = _content_to_text(content)

        if role == "user":
            if _is_tool_result_msg(msg):
                breakdown.tool_result_tokens += estimate_tokens(
                    content_text, content_type="tool_result"
                )
                breakdown.tool_result_count += 1
            else:
                breakdown.user_tokens += estimate_tokens(content_text)
                breakdown.user_message_count += 1
        elif role == "assistant":
            breakdown.assistant_tokens += estimate_tokens(content_text)
            breakdown.assistant_message_count += 1

    return breakdown
