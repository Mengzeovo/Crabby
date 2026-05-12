from __future__ import annotations

import json
from pathlib import Path

import pytest

from memory import Session
from personas.loader import parse_persona_file
from personas.models import Persona, PersonaState
from personas.registry import PersonaRegistry
from personas.runtime import apply_persona_selection, resolve_active_persona
from personas.router import (
    PersonaRouter,
    _build_persona_catalog,
    _parse_route_result,
)


def test_parse_persona_file(tmp_path: Path) -> None:
    persona_file = tmp_path / "PERSONA.md"
    persona_file.write_text(
        "---\n"
        "id: mentor\n"
        "title: 导师\n"
        "description: Teach things clearly\n"
        "routing_hints:\n"
        "  - explain\n"
        "examples:\n"
        "  - explain this to me\n"
        "---\n\n"
        "# Persona Body\n",
        encoding="utf-8",
    )

    persona = parse_persona_file(persona_file)

    assert persona is not None
    assert persona.id == "mentor"
    assert persona.title == "导师"
    assert persona.routing_hints == ["explain"]
    assert persona.examples == ["explain this to me"]
    assert "Persona Body" in persona.body


def test_persona_registry_discovers_personas(tmp_path: Path) -> None:
    persona_dir = tmp_path / "mentor"
    persona_dir.mkdir()
    (persona_dir / "PERSONA.md").write_text(
        "---\n"
        "id: mentor\n"
        "title: 导师\n"
        "description: Explain things clearly\n"
        "---\n\n"
        "Body\n",
        encoding="utf-8",
    )

    registry = PersonaRegistry()

    assert registry.discover(tmp_path) == 1
    assert registry.get("mentor") is not None


def test_default_persona_assets_are_five_core_personas() -> None:
    repo_personas_dir = Path(__file__).resolve().parents[2] / "personas"
    registry = PersonaRegistry()

    assert registry.discover(repo_personas_dir) == 5
    assert {persona.id for persona in registry.list_personas()} == {
        "secretary",
        "archivist",
        "researcher",
        "philosopher",
        "mentor",
    }


def test_parse_route_result_handles_fenced_or_plain_json() -> None:
    direct = _parse_route_result(
        '{"persona_id":"mentor","confidence":0.82,"reason":"clear teaching request","summary":"user wants a simple explanation"}'
    )
    fenced = _parse_route_result(
        '```json\n{"persona_id":"researcher","confidence":0.91,"reason":"needs evidence","summary":"user wants to test a claim"}\n```'
    )
    string_null = _parse_route_result(
        '{"persona_id":"null","confidence":0.33,"reason":"unclear","summary":"unclear intent"}'
    )

    assert direct is not None
    assert direct.persona_id == "mentor"
    assert direct.confidence == 0.82
    assert direct.summary == "user wants a simple explanation"
    assert fenced is not None
    assert fenced.persona_id == "researcher"
    assert fenced.confidence == 0.91
    assert fenced.summary == "user wants to test a claim"
    assert string_null is not None
    assert string_null.persona_id is None


def test_parse_route_result_rejects_invalid_json() -> None:
    assert _parse_route_result("not json") is None


def test_persona_model_defaults_are_auto_safe() -> None:
    persona = Persona(id="p1", title="P1", description="desc")

    assert persona.routing_hints == []
    assert persona.examples == []


def test_persona_catalog_is_sorted_by_id_for_cache_stability() -> None:
    catalog = _build_persona_catalog(
        [
            Persona(id="mentor", title="导师", description="Teach"),
            Persona(id="archivist", title="档案官", description="Archive"),
            Persona(id="secretary", title="秘书", description="Plan"),
        ]
    )

    payload = json.loads(catalog)

    assert [item["id"] for item in payload] == ["archivist", "mentor", "secretary"]


@pytest.mark.asyncio
async def test_persona_router_sends_all_personas_to_llm(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_chat_completion(**kwargs):
        captured.update(kwargs)
        return {
            "content": [
                {
                    "type": "text",
                    "text": (
                        '{"persona_id":"mentor","confidence":0.91,'
                        '"reason":"teaching request","summary":"needs explanation"}'
                    ),
                }
            ]
        }

    monkeypatch.setattr(
        "personas.router.chat_completion",
        fake_chat_completion,
    )
    personas = [
        Persona(
            id="secretary",
            title="秘书",
            description="Task and schedule management",
            routing_hints=["待办", "日程", "提醒"],
            examples=["帮我整理今天要做的事"],
        ),
        Persona(
            id="archivist",
            title="档案官",
            description="Knowledge archive and links",
            routing_hints=["整理笔记", "第二大脑", "归档"],
            examples=["帮我建立一个知识地图"],
        ),
        Persona(
            id="researcher",
            title="研究员",
            description="Evidence and skeptical analysis",
            routing_hints=["研究", "查证", "反例"],
            examples=["找证据和反例验证一下"],
        ),
        Persona(
            id="philosopher",
            title="哲学家",
            description="Values and life direction",
            routing_hints=["人生规划", "价值观", "意义"],
            examples=["这个选择和我的价值观一致吗"],
        ),
        Persona(
            id="mentor",
            title="导师",
            description="Teaching and learning feedback",
            routing_hints=["教我", "讲解", "学习路径"],
            examples=["像老师一样解释"],
        ),
    ]
    for persona in personas:
        persona.body = f"FULL_BODY_FOR_{persona.id}"
        persona.source_path = f"/tmp/{persona.id}/PERSONA.md"

    result = await PersonaRouter(threshold=0.75).route(
        personas=personas,
        recent_user_turns=["用户说：像老师一样讲清楚这个概念。"],
    )

    assert result is not None
    assert result.persona_id == "mentor"

    messages = captured["messages"]
    assert isinstance(messages, list)
    content = messages[0]["content"]
    assert isinstance(content, str)
    for persona in personas:
        assert persona.id in content
        assert persona.body in content
        assert persona.source_path in content
    assert content.count('"id":') == 5
    assert "关键词预筛" not in content
    assert "feynman" not in content


@pytest.mark.asyncio
async def test_resolve_active_persona_updates_summary_before_lock() -> None:
    registry = PersonaRegistry()
    registry.register(
        Persona(
            id="mentor",
            title="导师",
            description="Explain things simply",
        )
    )

    class _Router:
        threshold = 0.75

        async def route(self, *, personas, recent_user_turns, existing_summary=""):
            return type(
                "Route",
                (),
                {
                    "persona_id": None,
                    "confidence": 0.42,
                    "reason": "intent still broad",
                    "summary": "用户想先理解一个概念，但还没说清具体侧重点",
                },
            )()

    session = Session()
    persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=_Router(),
        current_turn_text="解释一下这个概念",
    )

    assert persona is None
    assert session.persona_state.active_persona_id is None
    assert session.persona_state.route_summary == "用户想先理解一个概念，但还没说清具体侧重点"
    assert session.persona_state.last_route_confidence == 0.42
    assert session.persona_state.status == "unresolved"


@pytest.mark.asyncio
async def test_resolve_active_persona_low_confidence_clears_auto_persona() -> None:
    registry = PersonaRegistry()
    registry.register(
        Persona(
            id="mentor",
            title="导师",
            description="Explain things simply",
        )
    )

    class _Router:
        threshold = 0.75

        async def route(self, *, personas, recent_user_turns, existing_summary=""):
            return type(
                "Route",
                (),
                {
                    "persona_id": "mentor",
                    "confidence": 0.41,
                    "reason": "weak teaching signal",
                    "summary": "用户可能想学习，但意图还不够明确",
                },
            )()

    session = Session()
    session.persona_state = PersonaState(
        mode="auto",
        active_persona_id="stale_persona",
        source="router",
        status="routed",
    )
    persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=_Router(),
        current_turn_text="这个怎么处理",
    )

    assert persona is None
    assert session.persona_state.active_persona_id is None
    assert session.persona_state.status == "low_confidence"
    assert session.persona_state.last_route_reason == "weak teaching signal"
    assert session.persona_state.last_route_confidence == 0.41


@pytest.mark.asyncio
async def test_resolve_active_persona_locks_when_confident() -> None:
    registry = PersonaRegistry()
    registry.register(
        Persona(
            id="mentor",
            title="导师",
            description="Explain things simply",
        )
    )

    class _Router:
        threshold = 0.75
        calls = 0

        async def route(self, *, personas, recent_user_turns, existing_summary=""):
            self.calls += 1
            return type(
                "Route",
                (),
                {
                    "persona_id": "mentor",
                    "confidence": 0.88,
                    "reason": "clear teaching request",
                    "summary": "用户需要一个面向新手的概念解释",
                },
            )()

    router = _Router()
    session = Session()
    persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=router,
        current_turn_text="像教新手一样讲明白",
    )

    assert persona is not None
    assert persona.id == "mentor"
    assert session.persona_state.active_persona_id == "mentor"
    assert session.persona_state.status == "routed"
    assert session.persona_state.route_summary == "用户需要一个面向新手的概念解释"
    assert router.calls == 1

    class _UnexpectedRouter:
        threshold = 0.75

        async def route(self, *, personas, recent_user_turns, existing_summary=""):
            raise AssertionError("locked auto persona should not reroute")

    second_persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=_UnexpectedRouter(),
        current_turn_text="现在帮我整理待办",
    )

    assert second_persona is not None
    assert second_persona.id == "mentor"


@pytest.mark.asyncio
async def test_manual_and_none_modes_replace_auto_persona() -> None:
    registry = PersonaRegistry()
    registry.register(
        Persona(
            id="researcher",
            title="研究员",
            description="Research things",
        )
    )
    registry.register(
        Persona(
            id="mentor",
            title="导师",
            description="Explain things simply",
        )
    )

    class _Router:
        threshold = 0.75

        async def route(self, *, personas, recent_user_turns, existing_summary=""):
            raise AssertionError("manual and none modes should not call the router")

    session = Session()
    session.persona_state = PersonaState(
        mode="auto",
        active_persona_id="researcher",
        source="router",
        status="routed",
    )

    apply_persona_selection(
        session,
        mode="manual",
        manual_persona_id="mentor",
    )
    persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=_Router(),
        current_turn_text="像老师一样解释",
    )
    assert persona is not None
    assert persona.id == "mentor"
    assert session.persona_state.active_persona_id == "mentor"
    assert session.persona_state.source == "manual"

    apply_persona_selection(
        session,
        mode="none",
        manual_persona_id=None,
    )
    persona = await resolve_active_persona(
        session,
        persona_registry=registry,
        persona_router=_Router(),
        current_turn_text="继续解释",
    )
    assert persona is None
    assert session.persona_state.active_persona_id is None
    assert session.persona_state.status == "disabled"
