"""Persona routing logic."""

from __future__ import annotations

import json
import logging
import re

from config import settings
from llm.client import chat_completion
from personas.models import Persona, PersonaRouteResult

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class PersonaRouter:
    """Route user intent to a persona with best-effort confidence scoring."""

    def __init__(self, threshold: float | None = None) -> None:
        self.threshold = (
            settings.persona_router_threshold if threshold is None else threshold
        )

    async def route(
        self,
        *,
        personas: list[Persona],
        recent_user_turns: list[str],
        existing_summary: str = "",
    ) -> PersonaRouteResult | None:
        if not personas or not recent_user_turns:
            return None

        routing_context = _build_routing_context(
            recent_user_turns=recent_user_turns,
            existing_summary=existing_summary,
        )
        if not routing_context:
            return None

        persona_catalog = _build_persona_catalog(personas)
        valid_ids = ", ".join(persona.id for persona in personas)

        system = (
            "你是 Crabby 的人格路由分类器。\n"
            "你会收到所有候选人格的完整 PERSONA.md 信息和当前用户上下文。\n"
            "请根据用户当前意图选择唯一最匹配、最应该被插入系统提示词的人格。\n"
            f"persona_id 只能是这些值之一，或 null: {valid_ids}。\n"
            "只能返回 JSON，字段必须包含 persona_id、confidence、reason、summary。\n"
            "如果意图仍不清楚，或没有人格匹配，请将 persona_id 设为 null，confidence 不超过 0.50。\n"
            "confidence 必须是 0 到 1 之间的数字。"
        )
        messages = [
            {
                "role": "user",
                "content": (
                    "全部候选人格（由 PERSONA.md 解析得到，包含完整正文）:\n\n"
                    f"{persona_catalog}\n\n"
                    "路由上下文:\n"
                    f"{routing_context}\n\n"
                    '请返回类似 {"persona_id": "mentor", "confidence": 0.82, "reason": "...", "summary": "..."} 的 JSON。'
                ),
            }
        ]

        try:
            resp = await chat_completion(
                messages=messages,
                system=system,
                tools=None,
                max_tokens=300,
            )
        except Exception as exc:  # pragma: no cover - network/provider failures
            logger.warning("Persona router failed; falling back to neutral mode: %s", exc)
            return None

        content_blocks = resp.get("content", [])
        text = "\n".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        parsed = _parse_route_result(text)
        if parsed is None:
            logger.warning("Persona router returned non-JSON payload: %s", text[:200])
            return None
        return parsed


def _build_routing_context(
    *,
    recent_user_turns: list[str],
    existing_summary: str,
) -> str:
    parts: list[str] = []
    summary = existing_summary.strip()
    if summary:
        parts.append(f"已有路由摘要: {summary}")

    turns_block = "\n".join(
        f"{idx}. {turn.strip()}"
        for idx, turn in enumerate(recent_user_turns[-3:], start=1)
        if turn.strip()
    )
    if turns_block:
        parts.append(f"最近的用户消息:\n{turns_block}")
    return "\n\n".join(parts).strip()


def _build_persona_catalog(personas: list[Persona]) -> str:
    payload = [
        {
            "id": persona.id,
            "title": persona.title,
            "description": persona.description,
            "routing_hints": persona.routing_hints,
            "examples": persona.examples,
            "body": persona.body,
            "source_path": persona.source_path,
        }
        for persona in sorted(personas, key=lambda item: item.id)
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_route_result(text: str) -> PersonaRouteResult | None:
    if not text:
        return None

    raw = text.strip()
    match = _JSON_BLOCK_RE.search(raw)
    if match is not None:
        raw = match.group(0)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    persona_id = payload.get("persona_id")
    if persona_id is not None:
        normalized_persona_id = str(persona_id).strip()
        persona_id = (
            None
            if normalized_persona_id.lower() in {"", "none", "null"}
            else normalized_persona_id
        )

    return PersonaRouteResult(
        persona_id=persona_id,
        confidence=max(0.0, min(confidence, 1.0)),
        reason=str(payload.get("reason", "")).strip(),
        summary=str(payload.get("summary", "")).strip(),
    )
