"""Auto-save memory hooked into the conversation stream."""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import dataclass
from typing import Any

from config import settings
from llm.client import chat_completion
from llm.session_activity import start_session_activity, stop_session_activity
from llm.tool_executor import build_default_context, execute_tool_call
from memory import Session, SessionStore
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_AUTO_SAVE_ALLOWED_TOOLS = ["memory_search", "memory_write"]
DEFAULT_AUTO_SAVE_CONTEXT_MESSAGES = 4


@dataclass(frozen=True)
class AutoSaveJob:
    """Frozen review window captured when auto-save is triggered."""

    session_id: str
    conversation_id: str
    branch_fingerprint: str
    conversation_revision: int
    messages_to_review: list[dict[str, Any]]
    context_messages: list[dict[str, Any]]


# Single global queue for auto-save tasks.
# Stores frozen review windows; the daemon does not read live messages.
_auto_save_queue: asyncio.Queue[AutoSaveJob] = asyncio.Queue(maxsize=128)


def should_trigger_auto_save(session: Session) -> bool:
    """Return True when the session has accumulated enough turns to trigger auto-save."""
    return (
        settings.auto_save_interval > 0
        and session.turn_count > 0
        and session.turn_count % settings.auto_save_interval == 0
    )


def trigger_auto_save(session: Session) -> None:
    """Snapshot the current active conversation window into the auto-save queue."""
    try:
        job = _build_auto_save_job(session)
        if job is None:
            logger.debug(
                "Auto-save not queued for session %s: no new messages to review.",
                session.id,
            )
            return

        _auto_save_queue.put_nowait(job)
        logger.debug(
            "Triggered auto-save for session %s conversation %s "
            "(turn_count=%d, review_messages=%d)",
            job.session_id,
            job.conversation_id,
            session.turn_count,
            len(job.messages_to_review),
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
            job = await _auto_save_queue.get()
            try:
                if store.get(job.session_id) is None:
                    logger.warning(
                        "Session %s not found during auto-save; skipping.",
                        job.session_id,
                    )
                    continue
                await _process_auto_save(job, registry, store)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(
                    "Auto-save failed for session %s: %s",
                    job.session_id,
                    e,
                )
            finally:
                _auto_save_queue.task_done()
        except asyncio.CancelledError:
            logger.info("Auto-Save Daemon stopped.")
            break


async def _process_auto_save(
    job: AutoSaveJob,
    registry: ToolRegistry,
    store: SessionStore,
) -> bool:
    """Use the LLM to review a frozen window and save durable memories."""
    if not job.messages_to_review:
        logger.debug(
            "Auto-save skipped for session %s conversation %s: no messages.",
            job.session_id,
            job.conversation_id,
        )
        return False

    allowed_tools: list[str] = getattr(
        settings,
        "auto_save_allowed_tools",
        DEFAULT_AUTO_SAVE_ALLOWED_TOOLS,
    )
    tools_schema = [
        t for t in registry.to_anthropic_tools() if t["name"] in allowed_tools
    ]
    available_tool_names = {str(t.get("name")) for t in tools_schema}

    if "memory_write" not in available_tool_names:
        logger.warning(
            "Auto-save skipped: required memory_write tool is not registered "
            "within allowed tools (%s).",
            allowed_tools,
        )
        await _notify_visible_client(
            job.session_id,
            "Auto-save skipped: required memory_write tool is not registered.",
        )
        return False

    logger.info(
        "Processing auto-save for session %s conversation %s (%d messages)...",
        job.session_id,
        job.conversation_id,
        len(job.messages_to_review),
    )

    start_session_activity("auto_save", session_id=job.session_id)
    try:
        for context_messages, review_messages in _iter_review_chunks(job):
            succeeded = await _run_auto_save_chunk(
                job,
                registry,
                tools_schema,
                context_messages=context_messages,
                review_messages=review_messages,
            )
            if not succeeded:
                return False

            end_message_id = _last_message_id(review_messages)
            if end_message_id is None:
                logger.warning(
                    "Auto-save chunk for session %s conversation %s had no message IDs; "
                    "checkpoint not advanced.",
                    job.session_id,
                    job.conversation_id,
                )
                continue
            _advance_checkpoint(store, job, end_message_id)
    finally:
        stop_session_activity("auto_save", session_id=job.session_id)

    logger.info("Auto-save complete for session %s.", job.session_id)
    await _notify_visible_client(
        job.session_id,
        "已自动审阅最近的对话，并保存其中有长期价值的记忆。",
    )
    return True


async def _run_auto_save_chunk(
    job: AutoSaveJob,
    registry: ToolRegistry,
    tools_schema: list[dict[str, Any]],
    *,
    context_messages: list[dict[str, Any]],
    review_messages: list[dict[str, Any]],
) -> bool:
    agent_messages = [
        {
            "role": "user",
            "content": _build_review_input(context_messages, review_messages),
        }
    ]

    ctx = build_default_context(
        session_id=job.session_id,
        conversation_id=job.conversation_id,
        branch_fingerprint=job.branch_fingerprint,
    )
    max_iterations: int = getattr(settings, "auto_save_max_iterations", 10)

    unresolved_tool_error = False

    for _ in range(max_iterations):
        response = await chat_completion(
            messages=agent_messages,
            system=_auto_save_system_prompt(),
            tools=tools_schema,
            max_tokens=2048,
        )

        content_blocks = response.get("content", [])
        stop_reason = response.get("stop_reason", "end_turn")

        agent_messages.append({"role": "assistant", "content": content_blocks})

        if stop_reason != "tool_use":
            if unresolved_tool_error:
                logger.warning(
                    "Auto-save for session %s conversation %s ended after an "
                    "unresolved tool error; checkpoint not advanced.",
                    job.session_id,
                    job.conversation_id,
                )
                return False
            return True

        tool_results = []
        for block in content_blocks:
            if block.get("type") != "tool_use":
                continue

            tool_name = block["name"]
            tool_input = block["input"]
            tool_id = block["id"]

            llm_text, ui_payload = await execute_tool_call(
                registry,
                tool_name,
                tool_input,
                ctx=ctx,
                tool_id=tool_id,
            )
            if _tool_call_failed(ui_payload):
                unresolved_tool_error = True
            elif tool_name == "memory_write":
                unresolved_tool_error = False

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": llm_text,
            })

        agent_messages.append({"role": "user", "content": tool_results})

    logger.warning(
        "Auto-save for session %s exhausted %d iterations without a final response.",
        job.session_id,
        max_iterations,
    )
    return False


def _tool_call_failed(ui_payload: dict[str, Any]) -> bool:
    metadata = ui_payload.get("metadata")
    return (
        ui_payload.get("is_error") is True
        or ui_payload.get("status") == "error"
        or (isinstance(metadata, dict) and bool(metadata.get("error")))
    )


def _build_auto_save_job(session: Session) -> AutoSaveJob | None:
    conversation_id = session.active_conversation_id
    messages = copy.deepcopy(session.messages)
    if not messages:
        return None

    window_size = _auto_save_window_size()
    checkpoint = session.get_auto_save_checkpoint(conversation_id)
    checkpoint_message_id = (
        checkpoint.get("last_reviewed_message_id") if checkpoint else None
    )

    if checkpoint_message_id:
        checkpoint_index = _find_message_index(messages, str(checkpoint_message_id))
        if checkpoint_index is None:
            logger.warning(
                "Auto-save checkpoint message %s for session %s conversation %s "
                "was not found; falling back to the latest review window.",
                checkpoint_message_id,
                session.id,
                conversation_id,
            )
            start_index = max(0, len(messages) - window_size)
        else:
            start_index = checkpoint_index + 1
    else:
        start_index = max(0, len(messages) - window_size)

    if start_index >= len(messages):
        return None

    context_start = max(0, start_index - DEFAULT_AUTO_SAVE_CONTEXT_MESSAGES)
    return AutoSaveJob(
        session_id=session.id,
        conversation_id=conversation_id,
        branch_fingerprint=session.branch_fingerprint(conversation_id),
        conversation_revision=session.conversation_revision,
        messages_to_review=copy.deepcopy(messages[start_index:]),
        context_messages=copy.deepcopy(messages[context_start:start_index]),
    )


def _iter_review_chunks(
    job: AutoSaveJob,
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]]]]:
    chunk_size = _auto_save_window_size()
    chunks: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    for start in range(0, len(job.messages_to_review), chunk_size):
        end = start + chunk_size
        review_messages = copy.deepcopy(job.messages_to_review[start:end])
        if start == 0:
            context_messages = copy.deepcopy(job.context_messages)
        else:
            context_start = max(0, start - DEFAULT_AUTO_SAVE_CONTEXT_MESSAGES)
            context_messages = copy.deepcopy(
                job.messages_to_review[context_start:start]
            )
        chunks.append((context_messages, review_messages))
    return chunks


def _advance_checkpoint(
    store: SessionStore,
    job: AutoSaveJob,
    reviewed_message_id: str,
) -> None:
    session = store.get(job.session_id)
    if session is None:
        logger.warning(
            "Session %s disappeared after auto-save; checkpoint not persisted.",
            job.session_id,
        )
        return

    session.set_auto_save_checkpoint(
        job.conversation_id,
        message_id=reviewed_message_id,
        revision=job.conversation_revision,
        branch_fingerprint=job.branch_fingerprint,
    )
    store.persist(session)


def _auto_save_window_size() -> int:
    interval = max(1, int(getattr(settings, "auto_save_interval", 15) or 1))
    return interval * 2 + 4


def _find_message_index(messages: list[dict[str, Any]], message_id: str) -> int | None:
    for index, message in enumerate(messages):
        if message.get("message_id") == message_id:
            return index
    return None


def _last_message_id(messages: list[dict[str, Any]]) -> str | None:
    for message in reversed(messages):
        message_id = message.get("message_id")
        if message_id:
            return str(message_id)
    return None


def _build_review_input(
    context_messages: list[dict[str, Any]],
    review_messages: list[dict[str, Any]],
) -> str:
    context_text = _render_messages(context_messages) or "（无）"
    review_text = _render_messages(review_messages) or "（无）"
    return (
        "以下是 auto-save 需要审阅的对话片段。\n\n"
        "## 背景上下文\n"
        "只用于理解新增消息，不要仅凭这里写新记忆。\n\n"
        f"{context_text}\n\n"
        "## 待审阅新增消息\n"
        "只能从这里提取新记忆。若没有严格长期价值，直接结束，不要调用工具。\n\n"
        f"{review_text}"
    )


def _render_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "unknown")
        message_id = message.get("message_id", "?")
        prefix = f"[{role} {message_id}]"

        if "content" not in message:
            text = message.get("model_text", message.get("text", ""))
            if str(text).strip():
                lines.append(f"{prefix}: {text}")
            continue

        content = message.get("content")
        if isinstance(content, str):
            lines.append(f"{prefix}: {content}")
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    lines.append(f"{prefix}: {block.get('text', '')}")
                elif block.get("type") == "tool_use":
                    lines.append(f"{prefix}: [tool: {block.get('name', '?')}]")
                elif block.get("type") == "tool_result":
                    lines.append(
                        f"{prefix}: [tool_result] {block.get('content', '')}"
                    )
    return "\n\n".join(line for line in lines if line.strip())


def _auto_save_system_prompt() -> str:
    return (
        "你是一个不可见的后台长期记忆审阅代理。你的任务不是总结聊天，"
        "而是只把未来会话确实会复用的长期信息写入记忆。\n\n"
        "## 可写入的内容\n"
        "1. 用户稳定偏好、长期事实、目标或约束。\n"
        "2. 用户对 Crabby 行为的明确纠错、反馈或长期要求。\n"
        "3. 项目中的架构决策、稳定配置、接口约定、路径、命名规则或最终结论。\n"
        "4. 用户明确给出的可复用原始材料，例如配置片段、模板、命令或参考内容。\n\n"
        "## 必须跳过的内容\n"
        "1. 闲聊、临时执行过程、未确认猜测、一次性任务流水账。\n"
        "2. 泛泛的'我们讨论了/我们修改了'式摘要。\n"
        "3. 工具输出噪音、失败重试过程，除非其中包含稳定结论或可复用材料。\n"
        "4. 只出现在背景上下文里的内容。\n\n"
        "## 工具规则\n"
        "只能使用 memory_search 和 memory_write。写入前优先用 memory_search 检查既有记忆，"
        "避免重复；需要替换旧事实时使用 supersedes。"
        "如果待审阅新增消息里没有严格长期价值，直接结束，不要调用工具，也不要输出解释。"
    )


async def _notify_visible_client(session_id: str, message: str) -> None:
    from api.websocket import manager, notify_visible_client

    if session_id in manager.active_connections:
        await notify_visible_client(session_id, message)
    else:
        logger.debug(
            "Auto-save notification skipped: session %s has no active WS connection",
            session_id,
        )
