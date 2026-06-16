from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from llm import agent_runner
from llm.agent_runner import run_agent_turn
from memory import Session
from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry


class EchoInput(BaseModel):
    text: str


class EchoTool(Tool):
    name = "echo"
    description = "Echo text for tests."
    input_schema = EchoInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, EchoInput)
        return ToolResult(output=f"echo: {params.text}")


async def test_run_agent_turn_saves_final_assistant_message(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(agent_runner.settings, "llm_provider", "deepseek")

    async def fake_chat_completion(
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "done"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 3,
                "total_tokens": 13,
                "prompt_cache_hit_tokens": 7,
                "prompt_cache_miss_tokens": 3,
            },
        }

    monkeypatch.setattr(agent_runner, "chat_completion", fake_chat_completion)

    session = Session(id="agent-runner-test")
    reply = await run_agent_turn(
        session=session,
        registry=ToolRegistry(),
        system_prompt="system",
        tools_schema=[],
        ctx=Context(vault_path=tmp_path, conversation_id=session.id),
    )

    assert reply == "done"
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[0]["content"] == [{"type": "text", "text": "done"}]
    assert session.messages[0]["message_id"].startswith("m_")
    assert session.actual_usage_total == {
        "call_count": 1,
        "prompt_tokens": 10,
        "completion_tokens": 3,
        "total_tokens": 13,
        "reasoning_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 7,
        "prompt_cache_miss_tokens": 3,
        "prompt_cached_tokens": 0,
    }


async def test_run_agent_turn_executes_tool_then_final_reply(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(agent_runner.settings, "llm_provider", "deepseek")

    responses = [
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "echo",
                    "input": {"text": "hello"},
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 3,
                "total_tokens": 13,
                "prompt_cache_hit_tokens": 6,
                "prompt_cache_miss_tokens": 4,
            },
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "final"}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 4,
                "total_tokens": 24,
                "prompt_cache_hit_tokens": 15,
                "prompt_cache_miss_tokens": 5,
            },
        },
    ]

    seen_messages: list[list[dict[str, Any]]] = []

    async def fake_chat_completion(
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        seen_messages.append(messages)
        return responses.pop(0)

    monkeypatch.setattr(agent_runner, "chat_completion", fake_chat_completion)

    registry = ToolRegistry()
    registry.register(EchoTool())
    session = Session(id="agent-runner-tool-test")

    reply = await run_agent_turn(
        session=session,
        registry=registry,
        system_prompt="system",
        tools_schema=registry.to_anthropic_tools(),
        ctx=Context(vault_path=tmp_path, conversation_id=session.id),
    )

    assert reply == "final"
    assert session.messages[0]["role"] == "assistant"
    assert session.messages[0]["message_id"].startswith("m_")
    assert session.messages[1]["role"] == "user"
    assert session.messages[1]["content"][0]["type"] == "tool_result"
    assert session.messages[1]["content"][0]["tool_use_id"] == "toolu_1"
    assert session.messages[1]["content"][0]["content"].startswith(
        "[success] echo completed with status=success."
    )
    assert "summary: echo: hello" in session.messages[1]["content"][0]["content"]
    ui_payload = session.messages[1]["content"][0]["ui"]
    assert isinstance(ui_payload["elapsed_ms"], int)
    assert ui_payload["elapsed_ms"] >= 0
    assert ui_payload | {"elapsed_ms": ui_payload["elapsed_ms"]} == {
        "id": "toolu_1",
        "tool_use_id": "toolu_1",
        "name": "echo",
        "tool": "echo",
        "output": "echo: hello",
        "summary": "echo: hello",
        "input_summary": '{"text": "hello"}',
        "output_preview": "echo: hello",
        "detail_ref": "tool-result://echo/toolu_1",
        "detail_available": True,
        "metadata": {},
        "status": "success",
        "is_error": False,
        "is_truncated": False,
        "cache_path": None,
        "elapsed_ms": ui_payload["elapsed_ms"],
    }
    assert seen_messages[1][1]["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": session.messages[1]["content"][0]["content"],
        }
    ]
    assert session.messages[1]["message_id"].startswith("m_")
    assert session.messages[2]["role"] == "assistant"
    assert session.messages[2]["content"] == [{"type": "text", "text": "final"}]
    assert session.messages[2]["message_id"].startswith("m_")
    assert session.actual_usage_total == {
        "call_count": 2,
        "prompt_tokens": 30,
        "completion_tokens": 7,
        "total_tokens": 37,
        "reasoning_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 21,
        "prompt_cache_miss_tokens": 9,
        "prompt_cached_tokens": 0,
    }


async def test_run_agent_turn_default_iteration_limit_is_80(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setattr(agent_runner.settings, "llm_provider", "deepseek")
    calls = 0

    async def fake_chat_completion(
        *,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"toolu_{calls}",
                    "name": "missing_tool",
                    "input": {},
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 0,
                "total_tokens": 1,
            },
        }

    monkeypatch.setattr(agent_runner, "chat_completion", fake_chat_completion)

    session = Session(id="agent-runner-limit-test")
    reply = await run_agent_turn(
        session=session,
        registry=ToolRegistry(),
        system_prompt="system",
        tools_schema=[],
        ctx=Context(vault_path=tmp_path, conversation_id=session.id),
    )

    assert calls == agent_runner.DEFAULT_MAX_AGENT_ITERATIONS
    assert calls == 80
    assert reply == agent_runner.TOOL_ITERATION_LIMIT_MESSAGE
    assert session.actual_usage_total["call_count"] == 80
    assert session.actual_usage_total["total_tokens"] == 80
