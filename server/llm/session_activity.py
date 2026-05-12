"""Session activity tracking — 引用计数式会话活跃状态追踪。

移植自 Claude Code 的 sessionActivity.ts 设计思路：
- 每个活跃操作（API 调用、工具执行、Cron 任务）通过 start/stop 增减引用计数
- refcount > 0 表示 Agent 正忙，Cron Daemon 禁止触发
- refcount == 0 表示空闲，Cron 可以安全触发
- 可选注册心跳回调（如 WebSocket keepalive）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 全局状态
# ---------------------------------------------------------------------------

_refcount: int = 0
_active_reasons: dict[str, int] = {}  # reason → count
_heartbeat_callbacks: list[Callable[[], None]] = []
_heartbeat_task: asyncio.Task | None = None

HEARTBEAT_INTERVAL_S = 30  # 心跳间隔（秒）


# ---------------------------------------------------------------------------
# 心跳定时器
# ---------------------------------------------------------------------------


async def _heartbeat_loop() -> None:
    """周期性心跳循环，在 refcount > 0 时运行。"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL_S)
        logger.debug("session_keepalive_heartbeat: refcount=%d", _refcount)
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


def start_session_activity(reason: str) -> None:
    """标记一个活跃操作的开始。refcount 从 0→1 时启动心跳。

    Args:
        reason: 活跃原因标识（如 'api_call', 'tool_exec', 'cron_job'）
    """
    global _refcount
    _refcount += 1
    _active_reasons[reason] = _active_reasons.get(reason, 0) + 1

    if _refcount == 1:
        logger.debug("Session 进入忙碌: reason=%s", reason)
        if _heartbeat_callbacks:
            _start_heartbeat()


def stop_session_activity(reason: str) -> None:
    """标记一个活跃操作的结束。refcount 回到 0 时停止心跳。

    Args:
        reason: 与 start_session_activity 对应的原因标识
    """
    global _refcount
    if _refcount > 0:
        _refcount -= 1

    count = _active_reasons.get(reason, 0) - 1
    if count > 0:
        _active_reasons[reason] = count
    else:
        _active_reasons.pop(reason, None)

    if _refcount == 0:
        logger.debug("Session 回到空闲: last_reason=%s", reason)
        _stop_heartbeat()


def is_session_idle() -> bool:
    """检查当前会话是否空闲（refcount == 0）。"""
    return _refcount == 0


def get_session_activity_info() -> dict:
    """获取当前活跃状态的诊断信息。"""
    return {
        "refcount": _refcount,
        "active_reasons": dict(_active_reasons),
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
