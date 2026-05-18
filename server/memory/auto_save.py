"""Auto-save memory hooked into the conversation stream."""

from __future__ import annotations

import asyncio
import logging

from config import settings
from llm.client import chat_completion
from llm.tool_executor import build_default_context, execute_tool_call
from memory import Session, SessionStore
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Single global queue for auto-save tasks.
# Stores only session_id; the daemon re-loads the live session at drain time.
_auto_save_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=128)


def should_trigger_auto_save(session: Session) -> bool:
    """Return True when the session has accumulated enough turns to trigger auto-save."""
    return (
        settings.auto_save_interval > 0
        and session.turn_count > 0
        and session.turn_count % settings.auto_save_interval == 0
    )


def trigger_auto_save(session: Session) -> None:
    """Put a session_id entry into the auto-save queue."""
    try:
        _auto_save_queue.put_nowait(session.id)
        logger.debug(
            "Triggered auto-save for session %s (turn_count=%d)",
            session.id,
            session.turn_count,
        )
    except asyncio.QueueFull:
        logger.error(
            "Auto-save queue full (%d); skipping auto-save for session %s. "
            "Consider increasing auto_save_queue_maxsize or reducing auto_save_interval.",
            _auto_save_queue.maxsize,
            session.id,
        )
    except Exception as e:
        logger.error("Failed to enqueue auto_save for session %s: %s", session.id, e)


async def auto_save_daemon_loop(registry: ToolRegistry, store: SessionStore) -> None:
    """Background consumer that processes auto-save tasks sequentially."""
    logger.info(
        "Auto-Save Daemon started. Interval: %d turns, queue maxsize: %d",
        settings.auto_save_interval,
        _auto_save_queue.maxsize,
    )
    while True:
        try:
            session_id = await _auto_save_queue.get()
            try:
                session = store.get(session_id)
                if session is None:
                    logger.warning(
                        "Session %s not found during auto-save; skipping.",
                        session_id,
                    )
                    continue
                await _process_auto_save(session, registry)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(
                    "Auto-save failed for session %s: %s",
                    session_id,
                    e,
                )
            finally:
                _auto_save_queue.task_done()
        except asyncio.CancelledError:
            logger.info("Auto-Save Daemon stopped.")
            break


async def _process_auto_save(
    session: Session,
    registry: ToolRegistry,
) -> None:
    """Use the LLM to summarize and save memories based on the live session."""
    recent_messages = session.messages[-(settings.auto_save_interval * 2 + 4):]
    if not recent_messages:
        logger.debug(
            "Auto-save skipped for session %s: no messages.",
            session.id,
        )
        return

    logger.info("Processing auto-save for session %s...", session.id)

    # Only allow memory/knowledge tools (e.g. MemPalace MCP tools if connected)
    allowed_tools: list[str] = getattr(
        settings,
        "auto_save_allowed_tools",
        [
            "mempalace_add_drawer",
            "mempalace_diary_write",
            "mempalace_kg_add",
            "mempalace_kg_invalidate",
        ],
    )
    tools_schema = [
        t for t in registry.to_anthropic_tools() if t["name"] in allowed_tools
    ]

    if not tools_schema:
        logger.warning(
            "Auto-save skipped: none of the allowed tools (%s) are registered. "
            "Check auto_save_allowed_tools in settings or your MCP configuration.",
            allowed_tools,
        )
        from api.websocket import manager, notify_visible_client

        if session.id in manager.active_connections:
            await notify_visible_client(
                session.id,
                f"Auto-save skipped: none of the allowed tools ({allowed_tools}) are registered.",
            )
        return

    system_prompt = (
        "你是一个不可见的后台记忆代理。把你当成一位聪明的同事：你刚拿到一段对话记录，"
        "需要把其中关键事实、决策和结果永久归档。你的唯一任务是调用工具完成这件事。\n\n"
        "## 指南\n"
        '1. **不要外包理解：** 不要只写"我们处理了 X"。请提取精确上下文，'
        "例如具体路径、架构决策或代码配置。\n"
        "2. **保存可复用材料：** 如果出现原始代码片段、最终配置或有价值的原文引用，原样保存。\n"
        "3. **写日记摘要：** 简短总结发生了什么。\n"
        "4. 日记不要使用 AAAK 格式；请使用简洁、可读的人类语言或项目符号。\n"
        "5. 不要生成对话式文本回复；只能调用工具。\n\n"
        "## 优质记忆提取示例\n\n"
        "<example>\n"
        "对话片段:\n"
        "[user]: 把 session 存储从 Redis 改成本地 SQLite 吧，这样更容易部署。\n"
        "[assistant]: 可以。我已经更新 `server/memory/__init__.py`，改为使用 SQLite。\n\n"
        "<reasoning>\n"
        "代理识别出这是一个架构决策。不要写泛泛摘要，而要把具体技术选择和受影响组件归档，"
        "然后记录一条简短日记。\n"
        "</reasoning>\n"
        "工具调用:\n"
        "(调用知识归档工具：提取关键事实)\n"
        "(调用日记工具：记录架构变更)\n"
        "</example>\n\n"
        "<example>\n"
        "对话片段:\n"
        "[user]: 把这个 Nginx 配置加到我的 server block：location /api { proxy_read_timeout 300s; }\n"
        "<reasoning>\n"
        "代理看到了一段可复用的原始材料（Nginx 配置）。应原样保存，避免格式丢失，"
        "并记录一条简短日记。\n"
        "</reasoning>\n"
        "工具调用:\n"
        "(调用材料保存工具：原样保存配置)\n"
        "(调用日记工具：记录配置变更)\n"
        "</example>\n"
    )

    convo_text = []
    for m in recent_messages:
        role = m["role"]
        msg_content = m["content"]
        if isinstance(msg_content, str):
            convo_text.append(f"[{role}]: {msg_content}")
        elif isinstance(msg_content, list):
            for block in msg_content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    convo_text.append(f"[{role}]: {block.get('text', '')}")
                elif block.get("type") == "tool_use":
                    convo_text.append(f"[{role}]: [tool: {block.get('name', '?')}]")

    convo_str = "\n\n".join(convo_text)

    agent_messages = [
        {"role": "user", "content": f"以下是需要分析并保存的近期对话:\n\n{convo_str}"}
    ]

    ctx = build_default_context(
        session_id=session.id,
        conversation_id=session.active_conversation_id,
    )
    max_iterations: int = getattr(settings, "auto_save_max_iterations", 10)

    for _ in range(max_iterations):
        response = await chat_completion(
            messages=agent_messages,
            system=system_prompt,
            tools=tools_schema,
            max_tokens=2048,
        )

        content_blocks = response.get("content", [])
        stop_reason = response.get("stop_reason", "end_turn")

        agent_messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason != "tool_use":
            break

        tool_results = []
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_input = block["input"]
            tool_id = block["id"]

            llm_text, _ = await execute_tool_call(
                registry,
                tool_name,
                tool_input,
                ctx=ctx,
                tool_id=tool_id,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": llm_text,
            })

        agent_messages.append({"role": "user", "content": tool_results})
    else:
        # Exhausted all iterations without a final non-tool response.
        logger.warning(
            "Auto-save for session %s exhausted %d iterations without a final response.",
            session.id,
            max_iterations,
        )
        return  # Don't send "complete" notification.

    logger.info("Auto-save complete for session %s.", session.id)

    # Only notify sessions with an active WebSocket connection.
    # Isolated cron/loop sessions have no WS and would silently fail otherwise.
    from api.websocket import manager, notify_visible_client

    if session.id in manager.active_connections:
        await notify_visible_client(
            session.id,
            "已自动总结并保存最近的对话记忆。",
        )
    else:
        logger.debug(
            "Auto-save notification skipped: session %s has no active WS connection",
            session.id,
        )
