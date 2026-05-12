"""Cron Daemon — 后台心跳轮询 + 有序队列，定时唤醒 Agent 执行预设任务。

每 1 秒检查一次 cron_jobs.json 中的规则：
- 无论 Agent 是否正忙，始终扫描并将到期任务入队（绝不漏报）
- 用 croniter + last_fired_at 防止同一分钟内重复触发
- 入队后由独立的 consumer 协程按 FIFO 顺序串行消费
- 每个任务执行前添加 ms 级抖动防止瞬间拥堵
- 会话隔离：来自不同会话的任务在独立上下文中运行，
  来自同一会话的任务可复用该会话的上下文
- 执行完毕通过已有的 push_notification 推送结果给前端
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

from croniter import croniter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局任务队列（FIFO，按触发时间先后有序消费）
# ---------------------------------------------------------------------------
_job_queue: asyncio.Queue | None = None


def start_cron_daemon(
    registry,
    session_store,
    vault_path: Path,
) -> list[asyncio.Task]:
    """在 FastAPI startup 阶段注册后台心跳守护循环。"""
    global _job_queue
    _job_queue = asyncio.Queue()

    # 启动扫描器（生产者）和消费者
    scanner_task = asyncio.create_task(
        _cron_scanner(registry, session_store, vault_path),
        name="cron-scanner",
    )
    consumer_task = asyncio.create_task(
        _cron_consumer(registry, session_store, vault_path),
        name="cron-consumer",
    )
    logger.info("⏰ Cron Daemon 已启动（扫描器 + 队列消费者）。")
    return [scanner_task, consumer_task]


# ---------------------------------------------------------------------------
# 扫描器（生产者）：每秒检查到期任务，放入队列
# ---------------------------------------------------------------------------


async def _cron_scanner(registry, session_store, vault_path: Path) -> None:
    """无限循环：每 1 秒扫描 cron_jobs，将到期任务入队。

    ★ 核心变化：不再判断 Agent 是否空闲。
    即使 Agent 正忙，到期任务也会被放入队列排队等待，绝不漏报。
    """
    # 等待 3 秒让 startup 完成
    await asyncio.sleep(3)

    while True:
        try:
            from tools.cron import CronManager

            jobs = CronManager.load(vault_path)
            now = datetime.now()

            for job in jobs:
                if _should_fire(job, now):
                    logger.info("⏰ Cron 入队: [%s] %s", job.id, job.cron)
                    # 立即标记 last_fired_at 防止下一轮重复入队
                    CronManager.update_last_fired(vault_path, job.id)
                    await _job_queue.put(job)
        except Exception:
            logger.exception("⏰ Cron Scanner 轮询出错")

        await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# 消费者：从队列中按 FIFO 逐个取出并串行执行
# ---------------------------------------------------------------------------


async def _cron_consumer(registry, session_store, vault_path: Path) -> None:
    """从队列中逐个取出任务，会话优先，排队串行执行。

    核心原则（源自 Claude Code sessionActivity.ts 的 refcount 设计）：
      refcount > 0 意味着用户正在交互（api_call / tool_exec），Cron 必须让步。
      只有当 refcount == 0（会话空闲）时，Cron 任务才被允许开始执行。
    这保证了用户聊天永远具有最高优先级，定时任务绝不会抢占用户体验。
    """
    while True:
        job = await _job_queue.get()
        try:
            from llm.session_activity import is_session_idle

            # ★ 会话优先：等待 refcount 归零再执行
            waited = 0
            while not is_session_idle():
                if waited >= 1800:  # 30 分钟超时保护，防止死锁
                    logger.warning(
                        "⏰ Cron Job %s 等待会话空闲超时 (30min)，本次放弃",
                        job.id,
                    )
                    break
                await asyncio.sleep(1)
                waited += 1

            if waited >= 1800:
                # 超时放弃，继续处理队列中的下一个
                continue

            # ms 级抖动：打散可能的瞬间拥堵（主要防止文件 I/O 碰撞）
            await asyncio.sleep(random.uniform(0.001, 0.05))

            await _execute_cron_job(job, registry, session_store, vault_path)
        except Exception:
            logger.exception("⏰ Cron Consumer 执行任务 %s 失败", job.id)
        finally:
            _job_queue.task_done()


# ---------------------------------------------------------------------------
# 时间匹配
# ---------------------------------------------------------------------------


def _should_fire(job, now: datetime) -> bool:
    """判断一个 job 在当前时间窗口是否应该触发。

    逻辑：
    1. 用 croniter 计算上一次匹配时刻
    2. 根据 Cron 表达式是 5 字段还是 6 字段（秒级），确定当前时间窗口（分钟或秒）
    3. 如果上一次匹配恰好落在当前时间窗口内
    4. 并且 last_fired_at 不在此窗口内 → 触发
    """
    fields_count = len(job.cron.strip().split())
    if fields_count not in (5, 6):
        return False

    has_seconds = fields_count == 6

    try:
        cron = croniter(
            job.cron,
            now + timedelta(microseconds=1),
            second_at_beginning=has_seconds,
        )
        prev_fire: datetime = cron.get_prev(datetime)
    except (ValueError, KeyError):
        return False

    # 检查是否包含秒级精度（以空格分隔的字段数为 6）
    # 注意：croniter 中如果字段为 6 个，第一个字段表示秒。
    if has_seconds:
        # 秒级精度："当前这一秒"，把微秒归零
        window_start = now.replace(microsecond=0)
        window_end = window_start + timedelta(seconds=1)
    else:
        # 分钟级精度："当前这一分钟"，把秒和微秒归零
        window_start = now.replace(second=0, microsecond=0)
        window_end = window_start + timedelta(minutes=1)

    # 上次匹配时间不在本窗口，说明本窗口不该触发
    if not (window_start <= prev_fire < window_end):
        return False

    # 检查是否已经在本时间窗口内触发过（防止在同一秒/同一分内重复触发）
    if job.last_fired_at:
        try:
            last = datetime.fromisoformat(job.last_fired_at)
            if window_start <= last < window_end:
                return False  # 已经在此时间窗口触发过了
        except (ValueError, TypeError):
            pass

    return True


# ---------------------------------------------------------------------------
# 任务执行（含会话隔离逻辑）
# ---------------------------------------------------------------------------


async def _execute_cron_job(job, registry, session_store, vault_path: Path) -> None:
    """执行一个 Cron Job，严格会话隔离。

    会话策略：
      ★ 每个定时任务永远在全新的隔离会话中执行，绝不复用已有会话。
        这从根本上杜绝了不同会话上下文互相污染的问题。
      ★ 如果任务有 source_session_id，执行结果的通知会被推送到来源会话，
        方便用户在创建任务的那个对话中看到结果。

    失败处理：
      - 循环任务：失败不影响下次正常触发
      - 单次任务：失败后清除 last_fired_at，允许下一个 cron 周期自动重试
    """
    from llm.agent_runner import DEFAULT_MAX_AGENT_ITERATIONS, run_agent_turn
    from llm.prompts import build_system_prompt
    from llm.session_activity import start_session_activity, stop_session_activity
    from llm.tool_executor import build_default_context
    from tools.cron import CronManager

    # 标记 session 为忙碌（refcount +1，阻止其他 Cron 和人类交互的并发）
    start_session_activity("cron_job")

    source_sid = getattr(job, "source_session_id", None)

    try:
        # ★ 始终新建隔离会话 — 干净的上下文
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        isolated_session_id = f"cron_{job.id}_{timestamp}"
        session = session_store.get_or_create(isolated_session_id)
        isolated_conversation_id = session.active_conversation_id
        logger.info(
            "⏰ Job %s 在隔离会话 %s 中执行（来源会话: %s）",
            job.id, isolated_session_id, source_sid or "无",
        )

        # 注入 Cron 触发内容作为"虚拟用户消息"
        session.add_user_message(
            f"[系统定时任务触发] 任务 ID: {job.id}\n"
            f"Cron 表达式: {job.cron}\n"
            f"请执行以下指令：\n\n{job.prompt}"
        )

        system = build_system_prompt()
        tools_schema = registry.to_anthropic_tools()
        ctx = build_default_context(
            session_id=isolated_session_id,
            conversation_id=isolated_conversation_id,
        )

        # 执行完整的 Agentic Tool Loop
        reply = await run_agent_turn(
            session=session,
            registry=registry,
            system_prompt=system,
            tools_schema=tools_schema,
            ctx=ctx,
            max_iterations=DEFAULT_MAX_AGENT_ITERATIONS,
        )

        session_store.persist(session)

        # 处理非循环任务：成功时自动删除
        if not job.recurring:
            CronManager.delete(vault_path, job.id)
            logger.info("⏰ 单次任务 %s 已执行并自动删除", job.id)

        # ★ 推送通知到来源会话（如果有的话），否则推送到隔离会话
        from api.websocket import push_notification

        notify_target = source_sid if source_sid else isolated_session_id
        summary = reply[:300] if reply else "(无文本输出)"
        await push_notification(
            notify_target,
            f"⏰ 定时任务 [{job.id}] 已完成！\n"
            f"执行会话: {isolated_session_id}\n{summary}",
        )

        logger.info("⏰ Cron Job %s 执行完成", job.id)

    except Exception:
        logger.exception("⏰ Cron Job %s 执行失败", job.id)

        # ★ 单次任务失败时，清除 last_fired_at 允许下一轮重试
        if not job.recurring:
            CronManager.update_last_fired(vault_path, job.id, clear=True)
            logger.info("⏰ 单次任务 %s 失败，已重置触发标记以允许重试", job.id)
    finally:
        stop_session_activity("cron_job")
