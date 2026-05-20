"""Session activity tracking — 引用计数式会话活跃状态追踪。

移植自 Claude Code 的 sessionActivity.ts 设计思路：
- 每个活跃操作（API 调用、工具执行、Cron 任务）通过 start/stop 增减引用计数
- refcount > 0 表示 Agent 正忙，Cron Daemon 禁止触发
- refcount == 0 表示空闲，Cron 可以安全触发
- 可选注册心跳回调（如 WebSocket keepalive）
- 支持 per-session refcount 和全局总计数
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------

# Per-session refcount: session_id -> active operation count
# session_id="" represents callers that don't pass a session_id (backward compat)
_refcount: dict[str, int] = defaultdict(int)
# Per-session active reasons: session_id -> { reason -> count }
_active_reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_heartbeat_callbacks: list[Callable[[], None]] = []
_heartbeat_task: asyncio.Task | None = None

HEARTBEAT_INTERVAL_S = 30  # 心跳间隔（秒）


# ---------------------------------------------------------------------------
# 心跳定时器
# ---------------------------------------------------------------------------


async def _heartbeat_loop() -> None:
    """周期性心跳循环，在全局总 refcount > 0 时运行。"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        total = sum(_refcount.values())
        logger.debug("session_keepalive_heartbeat: total_refcount=%d", total)
        for cb in _heartbeat_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("心跳回调执行失败")


def _start_heartbeat() -> None:
    """启动心跳定时器（如果尚未运行）。"""
    global _heartbeat_task
    if _heartbeat_task is None or _heartbeat_task.done():
        try:
            loop = asyncio.get_running_loop()
            _heartbeat_task = loop.create_task(_heartbeat_loop())
        except RuntimeError:
            # 没有正在运行的事件循环（例如在测试中）
            pass


def _stop_heartbeat() -> None:
    """停止心跳定时器。"""
    global _heartbeat_task
    if _heartbeat_task is not None and not _heartbeat_task.done():
        _heartbeat_task.cancel()
        _heartbeat_task = None


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


def start_session_activity(reason: str, session_id: str = "") -> None:
    """标记一个活跃操作的开始。全局总 refcount 从 0→1 时启动心跳。

    Args:
        reason: 活跃原因标识（如 'api_call', 'tool_exec', 'cron_job'）
        session_id: 会话 ID，默认为空字符串（全局累积）。
                   传入 session_id 时只影响该会话的计数器。
    """
    prev_total = sum(_refcount.values())
    _refcount[session_id] += 1
    _active_reasons[session_id][reason] += 1

    if prev_total == 0:
        logger.debug("Session 进入忙碌: session_id=%r reason=%s", session_id, reason)
        if _heartbeat_callbacks:
            _start_heartbeat()


def stop_session_activity(reason: str, session_id: str = "") -> None:
    """标记一个活跃操作的结束。全局总 refcount 回到 0 时停止心跳。

    Args:
        reason: 与 start_session_activity 对应的原因标识
        session_id: 会话 ID，默认为空字符串（全局累积）。
    """
    # 通过 .get 访问，避免 defaultdict 在 stop 一个从未 start 过的
    # session_id 时被默认创建 0 值条目（导致长跑时无界增长）。
    current = _refcount.get(session_id, 0)
    if current > 0:
        new_count = current - 1
        session_reasons = _active_reasons[session_id]
        count = session_reasons.get(reason, 0) - 1
        if count > 0:
            session_reasons[reason] = count
        else:
            session_reasons.pop(reason, None)

        if new_count == 0 and session_id != "":
            # 归零后立即清理命名 session 的条目，避免大量唯一 session_id
            # （如带时间戳的 loop_*）累积导致内存无界增长。
            # 全局桶 "" 是固定 key，不清理（保持现有调用方约定）。
            _refcount.pop(session_id, None)
            if session_id in _active_reasons and not _active_reasons[session_id]:
                del _active_reasons[session_id]
        else:
            _refcount[session_id] = new_count

    if sum(_refcount.values()) == 0:
        logger.debug("Session 回到空闲: session_id=%r last_reason=%s", session_id, reason)
        _stop_heartbeat()


def is_session_idle(session_id: str = "") -> bool:
    """检查会话是否空闲。

    Args:
        session_id: 为空时检查全局总计数是否为零；
                   指定 session_id 时只检查该会话的计数器。
    """
    if session_id:
        return _refcount.get(session_id, 0) == 0
    return sum(_refcount.values()) == 0


def get_session_activity_info() -> dict:
    """获取当前活跃状态的诊断信息。"""
    return {
        "refcount": dict(_refcount),
        "total_refcount": sum(_refcount.values()),
        "active_reasons": {sid: dict(reasons) for sid, reasons in _active_reasons.items()},
        "heartbeat_running": _heartbeat_task is not None
        and not _heartbeat_task.done(),
    }


def register_heartbeat_callback(cb: Callable[[], None]) -> None:
    """注册一个心跳回调（如 WebSocket keepalive sender）。"""
    _heartbeat_callbacks.append(cb)


def unregister_heartbeat_callback(cb: Callable[[], None]) -> None:
    """注销一个心跳回调。"""
    try:
        _heartbeat_callbacks.remove(cb)
    except ValueError:
        pass
    if not _heartbeat_callbacks:
        _stop_heartbeat()
