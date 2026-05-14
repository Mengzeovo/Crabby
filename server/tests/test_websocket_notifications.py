from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
import pytest
from starlette.websockets import WebSocketDisconnect

from api import websocket as websocket_api
from attachment_store import AttachmentStore
from memory import SessionStore
from skills import SkillRegistry
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


class LongFailInput(BaseModel):
    pass


LONG_FAILURE_OUTPUT = "failure detail\n" + ("x" * 800)


class LongFailTool(Tool):
    name = "long_fail"
    description = "Return a long failing tool result for tests."
    input_schema = LongFailInput

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output=LONG_FAILURE_OUTPUT, metadata={"exit_code": 7})


def _build_ws_app(tmp_path: Path) -> tuple[FastAPI, SessionStore]:
    session_store = SessionStore(storage_dir=tmp_path / "sessions")
    attachment_store = AttachmentStore(storage_dir=tmp_path / "attachments")

    websocket_api.set_registry(ToolRegistry())
    websocket_api.set_session_store(session_store)
    websocket_api.set_skill_registry(SkillRegistry())
    websocket_api.set_attachment_store(attachment_store)

    app = FastAPI()
    app.include_router(websocket_api.router)
    return app, session_store


def _collect_until_done(ws) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        payload = json.loads(ws.receive_text())
        events.append(payload)
        if payload["type"] == "done":
            return events


def test_pending_notifications_are_injected_ephemerally(monkeypatch, tmp_path: Path):
    recorded_messages: list[dict[str, Any]] = []

    async def fake_chat_completion_stream(*, messages, system, tools):
        recorded_messages.extend(messages)
        yield {"type": "text_delta", "text": "LLM reply."}
        yield {
            "type": "done",
            "response": {
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": "LLM reply."}],
            },
        }

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    app, store = _build_ws_app(tmp_path)
    session = store.get_or_create("session-1")
    session.pending_notifications.append("Background task finished.")
    store.persist(session)

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "hello"}))
            events = _collect_until_done(ws)

    assert [event["type"] for event in events] == [
        "assistant_prefix",
        "text_delta",
        "done",
    ]
    assert events[0]["text"] == "Background task finished.\n\n"

    recorded_payload = json.dumps(recorded_messages, ensure_ascii=False)
    assert "task_notification" in recorded_payload
    assert "Background task finished." in recorded_payload

    persisted = store.get("session-1")
    assert persisted is not None
    assert persisted.pending_notifications == []
    latest_user = next(message for message in reversed(persisted.messages) if message["role"] == "user")
    assert "Background task finished." not in json.dumps(latest_user, ensure_ascii=False)


def test_reasoning_delta_is_forwarded_and_persisted(monkeypatch, tmp_path: Path):
    async def fake_chat_completion_stream(*, messages, system, tools):
        yield {"type": "reasoning_delta", "text": "thinking"}
        yield {"type": "text_delta", "text": "final"}
        yield {
            "type": "done",
            "response": {
                "stop_reason": "end_turn",
                "content": [
                    {
                        "type": "reasoning_details",
                        "reasoning_details": [{"text": "thinking"}],
                    },
                    {"type": "text", "text": "final"},
                ],
            },
        }

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    app, store = _build_ws_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "hello"}))
            events = _collect_until_done(ws)

    assert [event["type"] for event in events] == [
        "reasoning_delta",
        "text_delta",
        "done",
    ]
    assert events[0]["text"] == "thinking"

    persisted = store.get("session-1")
    assert persisted is not None
    assistant_messages = [
        message for message in persisted.messages if message["role"] == "assistant"
    ]
    assert assistant_messages[-1]["content"][0] == {
        "type": "reasoning_details",
        "reasoning_details": [{"text": "thinking"}],
    }


def test_stream_usage_is_accumulated_across_tool_loop(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(websocket_api.settings, "llm_provider", "deepseek")
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
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            },
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "final"}],
            "usage": {
                "prompt_tokens": 150,
                "completion_tokens": 30,
                "total_tokens": 180,
                "prompt_cache_hit_tokens": 100,
                "prompt_cache_miss_tokens": 50,
                "completion_tokens_details": {"reasoning_tokens": 8},
            },
        },
    ]

    async def fake_chat_completion_stream(*, messages, system, tools):
        yield {"type": "done", "response": responses.pop(0)}

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    session_store = SessionStore(storage_dir=tmp_path / "sessions")
    attachment_store = AttachmentStore(storage_dir=tmp_path / "attachments")
    registry = ToolRegistry()
    registry.register(EchoTool())
    session_store.create("session-1")
    websocket_api.set_registry(registry)
    websocket_api.set_session_store(session_store)
    websocket_api.set_skill_registry(SkillRegistry())
    websocket_api.set_attachment_store(attachment_store)

    app = FastAPI()
    app.include_router(websocket_api.router)

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "hello"}))
            events = _collect_until_done(ws)

    done = events[-1]
    assert done["type"] == "done"
    assert done["message_id"].startswith("m_")
    assert done["user_message_id"].startswith("m_")
    assert done["context"]["actual_usage"] == {
        "call_count": 2,
        "prompt_tokens": 250,
        "completion_tokens": 50,
        "total_tokens": 300,
        "reasoning_tokens": 8,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 180,
        "prompt_cache_miss_tokens": 70,
        "prompt_cached_tokens": 0,
    }
    assert done["context"]["cumulative_usage"] == done["context"]["actual_usage"]
    assert any(event["type"] == "tool_result" for event in events)


def test_tool_result_event_contains_full_payload(monkeypatch, tmp_path: Path):
    responses = [
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_long_fail",
                    "name": "long_fail",
                    "input": {},
                }
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "final"}],
        },
    ]

    async def fake_chat_completion_stream(*, messages, system, tools):
        yield {"type": "done", "response": responses.pop(0)}

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    session_store = SessionStore(storage_dir=tmp_path / "sessions")
    attachment_store = AttachmentStore(storage_dir=tmp_path / "attachments")
    registry = ToolRegistry()
    registry.register(LongFailTool())
    session_store.create("session-1")
    websocket_api.set_registry(registry)
    websocket_api.set_session_store(session_store)
    websocket_api.set_skill_registry(SkillRegistry())
    websocket_api.set_attachment_store(attachment_store)

    app = FastAPI()
    app.include_router(websocket_api.router)

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "hello"}))
            events = _collect_until_done(ws)

    tool_result = next(event for event in events if event["type"] == "tool_result")
    assert tool_result["id"] == "toolu_long_fail"
    assert tool_result["tool_use_id"] == "toolu_long_fail"
    assert tool_result["name"] == "long_fail"
    assert tool_result["status"] == "error"
    assert tool_result["is_error"] is True
    assert tool_result["metadata"]["exit_code"] == 7
    assert tool_result["output"] == LONG_FAILURE_OUTPUT
    assert len(tool_result["output"]) > 500

    persisted = session_store.get("session-1")
    assert persisted is not None
    tool_message = next(
        message
        for message in persisted.messages
        if message["role"] == "user" and isinstance(message.get("content"), list)
    )
    block = tool_message["content"][0]
    assert block["ui"]["status"] == "error"
    assert block["ui"]["output"] == LONG_FAILURE_OUTPUT


def test_tool_iteration_limit_emits_warning_then_done(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(websocket_api, "DEFAULT_MAX_AGENT_ITERATIONS", 1)

    async def fake_chat_completion_stream(*, messages, system, tools):
        yield {
            "type": "tool_use_start",
            "name": "echo",
            "id": "toolu_1",
        }
        yield {
            "type": "done",
            "response": {
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
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
            },
        }

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    session_store = SessionStore(storage_dir=tmp_path / "sessions")
    attachment_store = AttachmentStore(storage_dir=tmp_path / "attachments")
    registry = ToolRegistry()
    registry.register(EchoTool())
    session_store.create("session-1")
    websocket_api.set_registry(registry)
    websocket_api.set_session_store(session_store)
    websocket_api.set_skill_registry(SkillRegistry())
    websocket_api.set_attachment_store(attachment_store)

    app = FastAPI()
    app.include_router(websocket_api.router)

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "hello"}))
            events = _collect_until_done(ws)

    assert [event["type"] for event in events] == [
        "tool_start",
        "tool_result",
        "warning",
        "done",
    ]
    assert events[2]["message"] == "Tool call iteration limit exceeded (1 rounds)"
    assert events[-1]["message_id"] is None
    assert events[-1]["user_message_id"].startswith("m_")
    assert all(event["type"] != "error" for event in events)


def test_stream_usage_accumulates_across_session_turns(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(websocket_api.settings, "llm_provider", "openai")
    responses = [
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "first"}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "second"}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 6,
                "total_tokens": 26,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        },
    ]

    async def fake_chat_completion_stream(*, messages, system, tools):
        yield {"type": "done", "response": responses.pop(0)}

    monkeypatch.setattr(
        websocket_api,
        "chat_completion_stream",
        fake_chat_completion_stream,
    )

    app, store = _build_ws_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        with client.websocket_connect("/sessions/session-1/conversations/root/ws") as ws:
            ws.send_text(json.dumps({"type": "message", "content": "first"}))
            first_events = _collect_until_done(ws)
            ws.send_text(json.dumps({"type": "message", "content": "second"}))
            second_events = _collect_until_done(ws)

    first_done = first_events[-1]
    second_done = second_events[-1]
    assert first_done["context"]["cumulative_usage"]["total_tokens"] == 15
    assert second_done["context"]["actual_usage"] == {
        "call_count": 1,
        "prompt_tokens": 20,
        "completion_tokens": 6,
        "total_tokens": 26,
        "reasoning_tokens": 3,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }
    assert second_done["context"]["cumulative_usage"] == {
        "call_count": 2,
        "prompt_tokens": 30,
        "completion_tokens": 11,
        "total_tokens": 41,
        "reasoning_tokens": 3,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "prompt_cached_tokens": 0,
    }

    persisted = store.get("session-1")
    assert persisted is not None
    assert persisted.actual_usage_total == second_done["context"]["cumulative_usage"]
    user_messages = [
        message for message in persisted.messages if message["role"] == "user"
    ]
    assert user_messages[-1]["message_id"] == second_done["user_message_id"]
    assistant_messages = [
        message for message in persisted.messages if message["role"] == "assistant"
    ]
    assert assistant_messages[-1]["message_id"] == second_done["message_id"]


def test_websocket_rejects_unsafe_session_id(tmp_path: Path):
    app, _store = _build_ws_app(tmp_path)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/sessions/..%5Cescape/conversations/root/ws"
            ) as ws:
                ws.receive_text()

    assert exc_info.value.code == 1008
    assert not (tmp_path / "escape.json").exists()


def test_websocket_rejects_unsafe_conversation_id(tmp_path: Path):
    app, store = _build_ws_app(tmp_path)
    store.create("session-1")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect(
                "/sessions/session-1/conversations/..%5Cescape/ws"
            ) as ws:
                ws.receive_text()

    assert exc_info.value.code == 1008
    assert not (tmp_path / "escape.json").exists()
