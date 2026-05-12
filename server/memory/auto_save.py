"""Auto-save memory hooked into the conversation stream."""

from __future__ import annotations

import asyncio
import copy
import logging

from config import settings
from llm.client import chat_completion
from llm.tool_executor import build_default_context, execute_tool_call
from memory import Session
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# Single global queue for auto-save tasks
# (Session ID, cloned Session object to avoid mutations)
_auto_save_queue: asyncio.Queue[Session] = asyncio.Queue()


def trigger_auto_save(session: Session) -> None:
    """Put a snapshot of the session into the auto-save queue."""
    try:
        # Clone messages to prevent concurrent mutation issues
        cloned_session = copy.deepcopy(session)
        # Fast non-blocking put
        _auto_save_queue.put_nowait(cloned_session)
        logger.debug("Triggered auto-save for session %s (turn_count=%d)", session.id, session.turn_count)
    except Exception as e:
        logger.error("Failed to enqueue auto_save for session %s: %s", session.id, e)


async def auto_save_daemon_loop(registry: ToolRegistry) -> None:
    """Background consumer that processes auto-save tasks sequentially."""
    logger.info("🛠️ Auto-Save Daemon started. Interval: %d turns", settings.auto_save_interval)
    while True:
        try:
            session_snapshot = await _auto_save_queue.get()
            try:
                await _process_auto_save(session_snapshot, registry)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception("Auto-save failed for session %s: %s", session_snapshot.id, e)
            finally:
                _auto_save_queue.task_done()
        except asyncio.CancelledError:
            logger.info("🛑 Auto-Save Daemon stopped.")
            break


async def _process_auto_save(session: Session, registry: ToolRegistry) -> None:
    """Use the LLM to summarize and save memories based on the session."""
    recent_messages = session.messages[-(settings.auto_save_interval * 2 + 4):]
    if not recent_messages:
        return

    logger.info("⏳ Processing auto-save for session %s...", session.id)

    # 1. 只放行相关的知识库/记忆工具
    allowed_tools = [
        "mempalace_add_drawer",
        "mempalace_diary_write",
        "mempalace_kg_add",
        "mempalace_kg_invalidate"
    ]
    tools_schema = [t for t in registry.to_anthropic_tools() if t["name"] in allowed_tools]

    if not tools_schema:
        logger.warning("Auto-save aborted: mempalace tools not available.")
        return

    system_prompt = (
        "你是一个不可见的后台记忆代理。把自己当成一位聪明的同事：你刚拿到一段对话记录，"
        "需要把其中关键事实、决策和结果永久归档到 MemPalace。你的唯一任务是调用工具完成这件事。\n\n"
        "## 指南\n"
        "1. **不要外包理解：** 不要只写“我们处理了 X”。请用 `mempalace_kg_add` 提取精确上下文，"
        "例如具体路径、架构决策或代码配置。\n"
        "2. **保存可复用材料：** 如果出现原始代码片段、最终配置或有价值的原文引用，"
        "请用 `mempalace_add_drawer` 原样保存到 drawer。\n"
        "3. **写日记摘要：** 最后总是用 `mempalace_diary_write` 简短总结发生了什么。\n"
        "4. 日记不要使用 AAAK 格式；请使用简洁、可读的人类语言或项目符号。\n"
        "5. 不要生成对话式文本回复；只能调用工具。\n\n"
        "## 优质记忆提取示例\n\n"
        "<example>\n"
        "对话片段:\n"
        "[user]: 把 session 存储从 Redis 改成本地 SQLite 吧，这样更容易部署。\n"
        "[assistant]: 可以。我已经更新 `server/memory/__init__.py`，改为使用 SQLite。\n\n"
        "<reasoning>\n"
        "代理识别出这是一个架构决策。不要写泛泛摘要，而要把具体技术选择和受影响组件写入知识图谱，"
        "然后记录一条简短日记。\n"
        "</reasoning>\n"
        "工具调用:\n"
        "1. mempalace_kg_add({\"facts\": [\"LifeAssistantAgent 为了简化部署，使用 SQLite 作为 session 存储，而不是 Redis\", \"server/memory/__init__.py 负责 SQLite session 存储\"]})\n"
        "2. mempalace_diary_write({\"content\": \"将 session 存储架构从 Redis 迁移到 SQLite，以简化部署；已更新 memory 初始化文件。\"})\n"
        "</example>\n\n"
        "<example>\n"
        "对话片段:\n"
        "[user]: 把这个 Nginx 配置加到我的 server block：location /api { proxy_read_timeout 300s; }\n\n"
        "<reasoning>\n"
        "代理看到了一段可复用的原始材料（Nginx 配置）。应使用 drawer 工具原样保存，避免格式丢失。\n"
        "</reasoning>\n"
        "工具调用:\n"
        "1. mempalace_add_drawer({\"name\": \"nginx_api_timeout_config\", \"content\": \"location /api { proxy_read_timeout 300s; }\"})\n"
        "2. mempalace_diary_write({\"content\": \"新增 /api 的 Nginx 配置块，将 proxy_read_timeout 设置为 300 秒。\"})\n"
        "</example>\n"
    )

    convo_text = []
    for m in recent_messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            convo_text.append(f"[{role}]: {content}")
        elif isinstance(content, list):
            texts = [b["text"] for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                convo_text.append(f"[{role}]: {' '.join(texts)}")

    convo_str = "\n\n".join(convo_text)
    
    agent_messages = [
        {"role": "user", "content": f"以下是需要分析并保存的近期对话:\n\n{convo_str}"}
    ]

    ctx = build_default_context(
        session_id=session.id,
        conversation_id=session.active_conversation_id,
    )
    max_iterations = 5

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

            llm_text, _ = await execute_tool_call(registry, tool_name, tool_input, ctx=ctx)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": llm_text,
            })
        
        agent_messages.append({"role": "user", "content": tool_results})

    logger.info("✅ Auto-save complete for session %s.", session.id)

    from api.websocket import notify_visible_client

    await notify_visible_client(
        session.id,
        "✅ 已自动总结并保存最近的对话记忆到 MemPalace。",
    )
