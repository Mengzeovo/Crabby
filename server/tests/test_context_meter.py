"""Tests for server/llm/context_meter.py."""

from __future__ import annotations

import pytest

from llm.context_meter import (
    CONTEXT_LIMIT,
    ContextBreakdown,
    _cjk_heuristic,
    _content_to_text,
    _is_tool_result_msg,
    estimate_tokens,
    measure_context,
)


# ── estimate_tokens ────────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0
        assert estimate_tokens("", content_type="json_schema") == 0

    def test_plain_text_short(self):
        t = estimate_tokens("hello world")
        assert 2 <= t <= 4  # tiktoken: 2 tokens for this

    def test_cjk_text(self):
        t = estimate_tokens("你好世界")
        assert 3 <= t <= 6  # tiktoken cl100k_base: ~5 tokens for these 4 CJK chars

    def test_content_type_affects_fallback_ratio(self):
        """When tiktoken is unavailable, different content_type uses different ratios."""
        # The heuristic: code uses 2.5 ratio, plain uses 4.0.
        # For the same non-CJK input, code should yield more tokens.
        # We test via _cjk_heuristic directly since tiktoken is available.
        code_text = "a" * 100  # 100 non-CJK chars
        plain_tokens = _cjk_heuristic(code_text, 4.0)
        code_tokens = _cjk_heuristic(code_text, 2.5)
        # 100 / 4.0 = 25, 100 / 2.5 = 40
        assert code_tokens > plain_tokens
        assert code_tokens == 40
        assert plain_tokens == 25

    def test_json_schema_content_type(self):
        schema = '{"type":"object","properties":{"name":{"type":"string"}}}'
        t = estimate_tokens(schema, content_type="json_schema")
        assert t > 0

    def test_tool_result_content_type(self):
        result = "Search found 42 results matching your query."
        t = estimate_tokens(result, content_type="tool_result")
        assert t > 0

    def test_cjk_ratio_in_heuristic(self):
        """CJK characters use 1.7 ratio, non-CJK uses the content_type ratio."""
        text = "你好ab"  # 2 CJK + 2 non-CJK
        # With ratio=4.0: 2/1.7 + 2/4 = ~1.18 + 0.5 = ~1.68 → max(1, int(1.68)) = 1
        t = _cjk_heuristic(text, 4.0)
        assert t >= 1

    def test_cjk_only(self):
        text = "你好世界"  # 4 CJK chars
        t = _cjk_heuristic(text, 4.0)
        # 4 / 1.7 = ~2.35 → int = 2
        assert t == 2

    def test_max_one_token_minimum(self):
        """Single non-CJK character still counts as at least 1 token."""
        t = _cjk_heuristic("x", 4.0)
        assert t == 1


# ── _content_to_text ───────────────────────────────────────────────────────────

class TestContentToText:
    def test_string_passthrough(self):
        assert _content_to_text("hello") == "hello"

    def test_text_block(self):
        blocks = [{"type": "text", "text": "hello world"}]
        assert _content_to_text(blocks) == "hello world"

    def test_image_block(self):
        blocks = [{"type": "image", "source": {"media_type": "image/png"}}]
        assert _content_to_text(blocks) == "[image:image/png]"

    def test_tool_use_block(self):
        blocks = [{"type": "tool_use", "input": {"query": "test"}}]
        assert _content_to_text(blocks) == '{"query": "test"}'

    def test_tool_result_block(self):
        blocks = [{"type": "tool_result", "content": "42 results"}]
        assert _content_to_text(blocks) == "42 results"

    def test_unknown_block(self):
        blocks = [{"type": "unknown", "data": 123}]
        assert "unknown" in _content_to_text(blocks)

    def test_mixed_blocks(self):
        blocks = [
            {"type": "text", "text": "Hello"},
            {"type": "tool_result", "content": "result"},
        ]
        assert _content_to_text(blocks) == "Hello\nresult"

    def test_non_dict_block(self):
        blocks = ["plain string"]
        assert _content_to_text(blocks) == "plain string"

    def test_non_list_non_string(self):
        assert _content_to_text(123) == "123"


# ── _is_tool_result_msg ───────────────────────────────────────────────────────

class TestIsToolResultMsg:
    def test_str_content_is_not_tool_result(self):
        assert _is_tool_result_msg({"role": "user", "content": "hello"}) is False

    def test_tool_result_block_in_list(self):
        msg = {
            "role": "user",
            "content": [{"type": "tool_result", "content": "ok"}],
        }
        assert _is_tool_result_msg(msg) is True

    def test_tool_result_block_absent(self):
        msg = {
            "role": "user",
            "content": [{"type": "text", "text": "hello"}],
        }
        assert _is_tool_result_msg(msg) is False


# ── ContextBreakdown ──────────────────────────────────────────────────────────

class TestContextBreakdown:
    def test_total_tokens_is_sum(self):
        bd = ContextBreakdown(
            system_tokens=100,
            schema_tokens=50,
            user_tokens=20,
            assistant_tokens=30,
            tool_result_tokens=10,
        )
        assert bd.total_tokens == 210

    def test_to_dict_default_context_limit(self):
        bd = ContextBreakdown(system_tokens=100, assistant_tokens=100)
        d = bd.to_dict()
        assert d["context_limit"] == CONTEXT_LIMIT
        assert d["usage_percent"] == round(200 / CONTEXT_LIMIT * 100, 1)

    def test_to_dict_custom_context_limit(self):
        bd = ContextBreakdown(system_tokens=100, assistant_tokens=100)
        d = bd.to_dict(context_limit=500)
        assert d["context_limit"] == 500
        assert d["usage_percent"] == 40.0

    def test_to_dict_zero_limit_returns_zero_percent(self):
        bd = ContextBreakdown(system_tokens=100)
        d = bd.to_dict(context_limit=0)
        assert d["context_limit"] == 0
        assert d["usage_percent"] == 0.0

    def test_to_log_line(self):
        bd = ContextBreakdown(
            system_tokens=100,
            schema_tokens=50,
            user_tokens=20,
            assistant_tokens=30,
            tool_result_tokens=10,
            message_count=5,
        )
        line = bd.to_log_line(context_limit=200_000)
        assert "system=100" in line
        assert "schema=50" in line
        assert "total=210" in line
        assert "msgs=5" in line

    def test_to_log_line_with_provider_limit(self):
        bd = ContextBreakdown(system_tokens=100, assistant_tokens=100)
        line = bd.to_log_line(context_limit=1000)
        assert "total=200/1000" in line
        assert "(20.0%)" in line


# ── measure_context ───────────────────────────────────────────────────────────

class TestMeasureContext:
    def test_empty_context(self):
        bd = measure_context("", None, [])
        assert bd.total_tokens == 0
        assert bd.message_count == 0

    def test_system_prompt_tokens(self):
        bd = measure_context("You are a helpful assistant.", None, [])
        assert bd.system_tokens > 0
        assert bd.total_tokens == bd.system_tokens

    def test_schema_tokens_use_json_schema_type(self, monkeypatch):
        """schema_tokens should be estimated with content_type='json_schema'."""
        # Patch estimate_tokens to record the content_type argument
        recorded: dict = {}

        def fake_estimate(text, *, content_type="plain"):
            recorded["content_type"] = content_type
            return 1

        monkeypatch.setattr("llm.context_meter.estimate_tokens", fake_estimate)
        measure_context("sys", [{"type": "object"}], [])
        assert recorded["content_type"] == "json_schema"

    def test_tool_result_messages_use_tool_result_type(self, monkeypatch):
        """tool_result role messages should be counted as tool_result tokens."""
        recorded: dict = {}

        def fake_estimate(text, *, content_type="plain"):
            recorded["content_type"] = content_type
            return 1

        monkeypatch.setattr("llm.context_meter.estimate_tokens", fake_estimate)
        measure_context(
            "",
            None,
            [
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "ok"}],
                }
            ],
        )
        assert recorded["content_type"] == "tool_result"

    def test_user_message_count(self):
        bd = measure_context(
            "",
            None,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "again"},
            ],
        )
        assert bd.user_message_count == 2
        assert bd.assistant_message_count == 1

    def test_tool_result_not_counted_as_user(self):
        bd = measure_context(
            "",
            None,
            [
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "ok"}],
                },
            ],
        )
        assert bd.user_message_count == 0
        assert bd.tool_result_count == 1

    def test_cjk_in_user_message(self):
        bd = measure_context("", None, [{"role": "user", "content": "你好"}])
        assert bd.user_tokens > 0
        assert bd.user_message_count == 1
