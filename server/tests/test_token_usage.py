from __future__ import annotations

import json

import pytest

import llm.client as client
from llm.client import (
    _apply_provider_request_options,
    _build_openai_params,
    _convert_message_to_openai,
    _convert_openai_response,
)
from llm.output_adapters import OpenAICompatibleStreamAdapter
from llm.providers import get_provider_preset, supports_streaming_tool_calls
from llm.token_usage import (
    TokenUsageAccumulator,
    context_with_actual_usage,
    merge_usage_snapshot,
)


def test_openai_response_preserves_usage():
    converted = _convert_openai_response(
        {
            "model": "MiniMax-M2.7",
            "choices": [
                {
                    "message": {
                        "content": "done",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 25,
                "total_tokens": 125,
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        }
    )

    assert converted["content"] == [{"type": "text", "text": "done"}]
    assert converted["usage"]["total_tokens"] == 125
    assert converted["usage"]["completion_tokens_details"]["reasoning_tokens"] == 7


def test_openai_reasoning_details_round_trip_to_history():
    converted = _convert_openai_response(
        {
            "model": "MiniMax-M2.7",
            "choices": [
                {
                    "message": {
                        "reasoning_details": [{"text": "think"}],
                        "content": "done",
                    },
                }
            ],
        }
    )

    assert converted["content"][0] == {
        "type": "reasoning_details",
        "reasoning_details": [{"text": "think"}],
    }

    messages = _convert_message_to_openai(
        {
            "role": "assistant",
            "content": converted["content"],
        }
    )

    assert messages == [
        {
            "role": "assistant",
            "content": "done",
            "reasoning_details": [{"text": "think"}],
        }
    ]


def test_deepseek_stream_adapter_maps_reasoning_content():
    adapter = OpenAICompatibleStreamAdapter(get_provider_preset("deepseek"))

    events = adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "thinking"},
                    "finish_reason": None,
                }
            ]
        }
    )
    events += adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"content": "done"},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    events.append(adapter.done_event())

    assert events[0] == {"type": "reasoning_delta", "text": "thinking"}
    assert events[1] == {"type": "text_delta", "text": "done"}
    assert events[-1]["response"]["content"] == [
        {
            "type": "reasoning_details",
            "reasoning_details": [{"text": "thinking"}],
        },
        {"type": "text", "text": "done"},
    ]


def test_qwen_stream_adapter_maps_reasoning_content():
    adapter = OpenAICompatibleStreamAdapter(get_provider_preset("qwen"))

    events = adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "thinking"},
                    "finish_reason": None,
                }
            ]
        }
    )
    events += adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"content": "done"},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    events.append(adapter.done_event())

    assert events[0] == {"type": "reasoning_delta", "text": "thinking"}
    assert events[1] == {"type": "text_delta", "text": "done"}
    assert events[-1]["response"]["content"] == [
        {
            "type": "reasoning_details",
            "reasoning_details": [{"text": "thinking"}],
        },
        {"type": "text", "text": "done"},
    ]


def test_deepseek_reasoning_content_round_trips_to_history():
    messages = _convert_message_to_openai(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "reasoning_details",
                    "reasoning_details": [{"text": "thinking"}],
                },
                {"type": "text", "text": "looking"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "lookup",
                    "input": {"q": "x"},
                },
            ],
        },
        preserve_reasoning_details=False,
        reasoning_output_shape="reasoning_content",
    )

    assert messages == [
        {
            "role": "assistant",
            "content": "looking",
            "reasoning_content": "thinking",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"q": "x"}',
                    },
                }
            ],
        }
    ]


def test_deepseek_request_preserves_reasoning_content_after_tool_result(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "deepseek-v4-pro")

    _url, _headers, body = _build_openai_params(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "reasoning_details",
                        "reasoning_details": [{"text": "thinking"}],
                    },
                    {"type": "text", "text": "I'll check."},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "lookup",
                        "input": {"q": "x"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": "result",
                    }
                ],
            },
        ],
        system="system",
        tools=[
            {
                "name": "lookup",
                "description": "",
                "input_schema": {"type": "object"},
            }
        ],
        max_tokens=64,
        provider="deepseek",
    )

    assistant_message = body["messages"][1]
    assert assistant_message["reasoning_content"] == "thinking"
    assert "reasoning_details" not in assistant_message
    assert body["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "result",
    }


def test_qwen_request_preserves_reasoning_content_after_tool_result(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "qwen3.6-plus")
    monkeypatch.setattr(client.settings, "llm_thinking_mode", "enabled")

    _url, _headers, body = _build_openai_params(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "reasoning_details",
                        "reasoning_details": [{"text": "thinking"}],
                    },
                    {"type": "text", "text": "I'll check."},
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "lookup",
                        "input": {"q": "x"},
                    },
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_1",
                        "content": "result",
                    }
                ],
            },
        ],
        system="system",
        tools=[
            {
                "name": "lookup",
                "description": "",
                "input_schema": {"type": "object"},
            }
        ],
        max_tokens=64,
        provider="qwen",
    )

    assistant_message = body["messages"][1]
    assert assistant_message["reasoning_content"] == "thinking"
    assert "reasoning_details" not in assistant_message
    assert body["enable_thinking"] is True
    assert body["preserve_thinking"] is True
    assert body["messages"][2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": "result",
    }


def test_minimax_stream_adapter_deduplicates_reasoning_details():
    adapter = OpenAICompatibleStreamAdapter(get_provider_preset("minimax"))

    events = adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"reasoning_details": [{"text": "think"}]},
                    "finish_reason": None,
                }
            ]
        }
    )
    events += adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {"reasoning_details": [{"text": "thinking"}]},
                    "finish_reason": None,
                }
            ]
        }
    )
    events.append(adapter.done_event())

    assert events[0] == {"type": "reasoning_delta", "text": "think"}
    assert events[1] == {"type": "reasoning_delta", "text": "ing"}
    assert events[-1]["response"]["content"] == [
        {
            "type": "reasoning_details",
            "reasoning_details": [{"text": "thinking"}],
        }
    ]


def test_openai_stream_adapter_ignores_unconfigured_reasoning_fields():
    adapter = OpenAICompatibleStreamAdapter(get_provider_preset("openai"))

    events = adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "reasoning_details": [{"text": "ignored"}],
                        "content": "done",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
    )
    events.append(adapter.done_event())

    assert events[0] == {"type": "text_delta", "text": "done"}
    assert events[-1]["response"]["content"] == [{"type": "text", "text": "done"}]


def test_openai_stream_adapter_preserves_tool_call_events():
    adapter = OpenAICompatibleStreamAdapter(get_provider_preset("openai"))

    events = adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"q"',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ]
        }
    )
    events += adapter.process_chunk(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ':"x"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )
    events.append(adapter.done_event())

    assert events[:4] == [
        {"type": "tool_use_start", "id": "call_1", "name": "lookup"},
        {"type": "tool_use_delta", "arguments_delta": '{"q"'},
        {"type": "tool_use_delta", "arguments_delta": ':"x"}'},
        {"type": "tool_use_end"},
    ]
    assert events[-1]["response"]["stop_reason"] == "tool_use"
    assert events[-1]["response"]["content"] == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "lookup",
            "input": {"q": "x"},
        }
    ]


def test_usage_accumulator_adds_openai_shape():
    accumulator = TokenUsageAccumulator(provider="openai")

    accumulator.add(
        {
            "prompt_tokens": 100,
            "completion_tokens": 25,
            "total_tokens": 125,
            "prompt_tokens_details": {"cached_tokens": 12},
            "completion_tokens_details": {"reasoning_tokens": 7},
            "input_tokens": 999,
            "prompt_cache_hit_tokens": 999,
        }
    )

    assert accumulator.to_dict() == {
        "call_count": 1,
        "prompt_tokens": 100,
        "completion_tokens": 25,
        "total_tokens": 125,
        "reasoning_tokens": 7,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 12,
    }


def test_usage_accumulator_adds_anthropic_shape():
    accumulator = TokenUsageAccumulator(provider="anthropic")

    accumulator.add(
        {
            "prompt_tokens": 999,
            "input_tokens": 40,
            "output_tokens": 10,
            "cache_creation_input_tokens": 3,
            "cache_read_input_tokens": 4,
            "output_tokens_details": {"reasoning_tokens": 2},
        }
    )

    assert accumulator.to_dict() == {
        "call_count": 1,
        "prompt_tokens": 40,
        "completion_tokens": 10,
        "total_tokens": 57,
        "reasoning_tokens": 2,
        "cache_creation_input_tokens": 3,
        "cache_read_input_tokens": 4,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }


def test_usage_accumulator_adds_deepseek_cache_fields():
    accumulator = TokenUsageAccumulator(provider="deepseek")

    accumulator.add(
        {
            "prompt_tokens": 120,
            "completion_tokens": 40,
            "total_tokens": 160,
            "prompt_cache_hit_tokens": 70,
            "prompt_cache_miss_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 999},
            "completion_tokens_details": {"reasoning_tokens": 11},
        }
    )

    assert accumulator.to_dict() == {
        "call_count": 1,
        "prompt_tokens": 120,
        "completion_tokens": 40,
        "total_tokens": 160,
        "reasoning_tokens": 11,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 70,
        "prompt_cache_miss_tokens": 50,
        "prompt_cached_tokens": 0,
    }


def test_usage_accumulator_merges_accumulated_snapshots():
    accumulator = TokenUsageAccumulator()

    accumulator.add_accumulated(
        {
            "call_count": 2,
            "prompt_tokens": 30,
            "completion_tokens": 10,
            "total_tokens": 40,
            "reasoning_tokens": 4,
            "prompt_cache_hit_tokens": 8,
        }
    )
    accumulator.add_accumulated(
        {
            "call_count": 1,
            "prompt_tokens": 20,
            "completion_tokens": 5,
            "total_tokens": 25,
            "prompt_cache_miss_tokens": 12,
        }
    )

    assert accumulator.to_dict() == {
        "call_count": 3,
        "prompt_tokens": 50,
        "completion_tokens": 15,
        "total_tokens": 65,
        "reasoning_tokens": 4,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 8,
        "prompt_cache_miss_tokens": 12,
        "prompt_cached_tokens": 0,
    }


def test_context_includes_legacy_cumulative_usage_without_call_count():
    context = context_with_actual_usage(
        {"total_tokens": 12},
        TokenUsageAccumulator(),
        {
            "prompt_tokens": 30,
            "completion_tokens": 11,
            "total_tokens": 41,
            "prompt_cache_hit_tokens": 8,
        },
    )

    assert context["cumulative_usage"] == {
        "call_count": 0,
        "prompt_tokens": 30,
        "completion_tokens": 11,
        "total_tokens": 41,
        "reasoning_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 8,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }
    assert "actual_usage" not in context


def test_context_uses_actual_usage_as_cumulative_fallback():
    usage = TokenUsageAccumulator(provider="deepseek")
    usage.add(
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 80,
        }
    )

    context = context_with_actual_usage({"total_tokens": 12}, usage)

    assert context["actual_usage"] == {
        "call_count": 1,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "reasoning_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 80,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }
    assert context["cumulative_usage"] == context["actual_usage"]


def test_stream_usage_snapshot_merge_keeps_latest_fields():
    usage = merge_usage_snapshot(None, {"input_tokens": 10})
    usage = merge_usage_snapshot(usage, {"output_tokens": 4})
    usage = merge_usage_snapshot(
        usage,
        {"completion_tokens_details": {"reasoning_tokens": 2}},
    )
    usage = merge_usage_snapshot(
        usage,
        {"completion_tokens_details": {"accepted_prediction_tokens": 1}},
    )

    assert usage == {
        "input_tokens": 10,
        "output_tokens": 4,
        "completion_tokens_details": {
            "reasoning_tokens": 2,
            "accepted_prediction_tokens": 1,
        },
    }


def test_openai_request_options_include_reasoning_controls(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "gpt-5.4-mini")
    monkeypatch.setattr(client.settings, "llm_reasoning_effort", " High ")
    monkeypatch.setattr(client.settings, "llm_reasoning_split", True)

    _url, _headers, body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=4096,
        provider="openai",
    )

    assert body["reasoning_effort"] == "high"
    assert "reasoning_split" not in body


def test_custom_openai_request_options_allow_reasoning_split(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "MiniMax-M2.7")
    monkeypatch.setattr(client.settings, "llm_reasoning_effort", " High ")
    monkeypatch.setattr(client.settings, "llm_reasoning_split", True)

    _url, _headers, body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=4096,
        provider="custom_openai",
    )

    assert body["reasoning_effort"] == "high"
    assert body["reasoning_split"] is True


@pytest.mark.parametrize(
    ("provider", "api_key_field", "expected_url"),
    [
        ("deepseek", "deepseek_api_key", "https://api.deepseek.com/chat/completions"),
        (
            "qwen",
            "bailian_coding_plan_api_key",
            "https://coding.dashscope.aliyuncs.com/v1/chat/completions",
        ),
        ("kimi", "kimi_api_key", "https://api.kimi.com/coding/v1/chat/completions"),
        ("minimax", "minimax_api_key", "https://api.minimax.io/v1/chat/completions"),
        (
            "zhipu",
            "zai_api_key",
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        ),
    ],
)
def test_builtin_openai_compatible_provider_params(
    monkeypatch,
    provider,
    api_key_field,
    expected_url,
):
    monkeypatch.setattr(client.settings, "llm_model", "model-id")
    monkeypatch.setattr(client.settings, "llm_api_key", "")
    monkeypatch.setattr(client.settings, "llm_base_url", "")
    monkeypatch.setattr(client.settings, "llm_thinking_mode", "")
    monkeypatch.setattr(client.settings, api_key_field, "provider-secret")

    url, headers, body = _build_openai_params(
        messages=[{"role": "user", "content": "hello"}],
        system="system",
        tools=[{"name": "read", "description": "", "input_schema": {"type": "object"}}],
        max_tokens=123,
        provider=provider,
    )

    assert url == expected_url
    assert headers["Authorization"] == "Bearer provider-secret"
    assert body["model"] == "model-id"
    assert body["max_tokens"] == 123
    assert body["messages"][0] == {"role": "system", "content": "system"}
    assert body["tools"][0]["function"]["name"] == "read"


def test_qwen_can_fall_back_to_dashscope_api_key(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "qwen3.6-plus")
    monkeypatch.setattr(client.settings, "llm_api_key", "")
    monkeypatch.setattr(client.settings, "llm_base_url", "")
    monkeypatch.setattr(client.settings, "llm_thinking_mode", "")
    monkeypatch.setattr(client.settings, "bailian_coding_plan_api_key", "")
    monkeypatch.setattr(client.settings, "dashscope_api_key", "dashscope-secret")

    url, headers, body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=123,
        provider="qwen",
    )

    assert url == "https://coding.dashscope.aliyuncs.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer dashscope-secret"
    assert body["model"] == "qwen3.6-plus"


def test_kimi_can_use_kimi_specific_api_key_and_base_url(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "kimi-for-coding")
    monkeypatch.setattr(client.settings, "llm_api_key", "")
    monkeypatch.setattr(client.settings, "llm_base_url", "")
    monkeypatch.setattr(client.settings, "kimi_api_key", "kimi-secret")
    monkeypatch.setattr(
        client.settings,
        "kimi_base_url",
        "https://api.kimi.com/coding/v1",
    )

    url, headers, body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=123,
        provider="kimi",
    )

    assert url == "https://api.kimi.com/coding/v1/chat/completions"
    assert headers["Authorization"] == "Bearer kimi-secret"
    assert body["model"] == "kimi-for-coding"


def test_generic_api_key_and_base_url_override_provider_defaults(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "model-id")
    monkeypatch.setattr(client.settings, "llm_api_key", "generic-secret")
    monkeypatch.setattr(client.settings, "llm_base_url", "https://proxy.example/v1")
    monkeypatch.setattr(client.settings, "deepseek_api_key", "provider-secret")

    url, headers, _body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=123,
        provider="deepseek",
    )

    assert url == "https://proxy.example/v1/chat/completions"
    assert headers["Authorization"] == "Bearer generic-secret"


def test_custom_openai_can_use_legacy_openai_env(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_model", "vendor-model")
    monkeypatch.setattr(client.settings, "llm_api_key", "")
    monkeypatch.setattr(client.settings, "llm_base_url", "")
    monkeypatch.setattr(client.settings, "openai_api_key", "legacy-secret")
    monkeypatch.setattr(client.settings, "openai_base_url", "https://vendor.example/v1")

    url, headers, _body = _build_openai_params(
        messages=[],
        system="system",
        tools=None,
        max_tokens=123,
        provider="custom_openai",
    )

    assert url == "https://vendor.example/v1/chat/completions"
    assert headers["Authorization"] == "Bearer legacy-secret"


def test_domestic_provider_reasoning_options_are_whitelisted(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_thinking_mode", "enabled")
    monkeypatch.setattr(client.settings, "llm_reasoning_effort", "high")
    monkeypatch.setattr(client.settings, "llm_reasoning_split", True)

    deepseek_body: dict[str, object] = {}
    _apply_provider_request_options(deepseek_body, "deepseek", max_tokens=4096)
    assert deepseek_body == {
        "thinking": {"type": "enabled"},
        "reasoning_effort": "high",
    }

    kimi_body: dict[str, object] = {}
    _apply_provider_request_options(kimi_body, "kimi", max_tokens=4096)
    assert kimi_body == {"thinking": {"type": "enabled"}}

    minimax_body: dict[str, object] = {}
    _apply_provider_request_options(minimax_body, "minimax", max_tokens=4096)
    assert minimax_body == {"reasoning_split": True}

    qwen_body: dict[str, object] = {}
    monkeypatch.setattr(client.settings, "llm_model", "qwen3.6-plus")
    _apply_provider_request_options(qwen_body, "qwen", max_tokens=4096)
    assert qwen_body == {
        "enable_thinking": True,
        "preserve_thinking": True,
    }

    zhipu_body: dict[str, object] = {}
    _apply_provider_request_options(zhipu_body, "zhipu", max_tokens=4096)
    assert zhipu_body == {"thinking": {"type": "enabled"}}


def test_qwen_coding_model_without_thinking_does_not_send_thinking(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_thinking_mode", "enabled")
    monkeypatch.setattr(client.settings, "llm_model", "qwen3-coder-next")

    body: dict[str, object] = {}
    _apply_provider_request_options(body, "qwen", max_tokens=4096)

    assert body == {}


def test_streaming_tool_support_is_provider_gated():
    assert supports_streaming_tool_calls("qwen") is False
    assert supports_streaming_tool_calls("deepseek") is True


def test_anthropic_request_options_include_thinking_budget(monkeypatch):
    monkeypatch.setattr(client.settings, "llm_thinking_mode", " enabled ")
    monkeypatch.setattr(client.settings, "llm_thinking_budget_tokens", 4096)

    body: dict[str, object] = {}
    _apply_provider_request_options(body, "anthropic", max_tokens=2048)

    assert body["thinking"] == {
        "type": "enabled",
        "budget_tokens": 2047,
    }


async def test_openai_compatible_stream_accepts_usage_only_final_chunk(monkeypatch):
    class FakeStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"reasoning_details": [{"text": "thinking"}]},
                            "finish_reason": None,
                        }
                    ]
                }
            )
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"content": "hi"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            yield "data: " + json.dumps(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 2,
                        "completion_tokens": 1,
                        "total_tokens": 3,
                    },
                }
            )
            yield "data: [DONE]"

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(client.httpx, "AsyncClient", FakeAsyncClient)

    events = [
        event
        async for event in client._openai_stream(
            messages=[],
            system="system",
            tools=None,
            max_tokens=10,
            provider="minimax",
        )
    ]

    assert events[0] == {"type": "reasoning_delta", "text": "thinking"}
    assert events[1] == {"type": "text_delta", "text": "hi"}
    assert events[-1]["response"]["content"] == [
        {
            "type": "reasoning_details",
            "reasoning_details": [{"text": "thinking"}],
        },
        {"type": "text", "text": "hi"},
    ]
    assert events[-1]["response"]["usage"]["total_tokens"] == 3
