"""Context meter — estimate token usage before each LLM call.

Provides a lightweight token estimator and a structured breakdown
of context composition (system prompt, tool schema, messages by role).

Token estimation uses a simple heuristic:
  - CJK characters: ~1.5 chars per token
  - ASCII/Latin: ~4 chars per token
  - Mixed content: weighted average based on CJK ratio

This is intentionally approximate — exact tokenization depends on the
provider's tokenizer, which we don't have access to for DeepSeek etc.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


# CJK Unicode ranges (common blocks)
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff"
    r"\U00020000-\U0002a6df\U0002a700-\U0002b73f"
    r"\U0002b740-\U0002b81f\U0002b820-\U0002ceaf]"
)


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string using CJK-aware heuristic."""
    if not text:
        return 0

    total_chars = len(text)
    cjk_chars = len(_CJK_RE.findall(text))
    non_cjk_chars = total_chars - cjk_chars

    # CJK: ~1.5 chars/token, non-CJK: ~4 chars/token
    tokens = cjk_chars / 1.5 + non_cjk_chars / 4.0
    return max(1, int(tokens))


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

    def to_dict(self) -> dict[str, Any]:
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
            "context_limit": CONTEXT_LIMIT,
            "usage_percent": round(self.total_tokens / CONTEXT_LIMIT * 100, 1),
        }

    def to_log_line(self) -> str:
        return (
            f"[context] system={self.system_tokens} schema={self.schema_tokens} "
            f"user={self.user_tokens} assistant={self.assistant_tokens} "
            f"tool_result={self.tool_result_tokens} "
            f"total={self.total_tokens}/{CONTEXT_LIMIT} "
            f"({self.total_tokens / CONTEXT_LIMIT * 100:.1f}%) "
            f"msgs={self.message_count}"
        )


# 256k token context window
CONTEXT_LIMIT = 256_000


def measure_context(
    system_prompt: str,
    tools_schema: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]],
) -> ContextBreakdown:
    """Measure token usage of the full context that will be sent to the LLM."""
    breakdown = ContextBreakdown()

    # System prompt
    breakdown.system_tokens = estimate_tokens(system_prompt)

    # Tool schema
    if tools_schema:
        schema_text = json.dumps(tools_schema, ensure_ascii=False)
        breakdown.schema_tokens = estimate_tokens(schema_text)

    # Messages
    breakdown.message_count = len(messages)
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        content_text = _content_to_text(content)
        tokens = estimate_tokens(content_text)

        if role == "user":
            # Check if this is a tool_result message
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            ):
                breakdown.tool_result_tokens += tokens
                breakdown.tool_result_count += 1
            else:
                breakdown.user_tokens += tokens
                breakdown.user_message_count += 1
        elif role == "assistant":
            breakdown.assistant_tokens += tokens
            breakdown.assistant_message_count += 1

    return breakdown
