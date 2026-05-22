"""Interactive Loop tools and cron-compatibility wrappers.

New interactive tools (frontend-driven, round-based):
- loop_start  : Launch an interactive loop session
- loop_ask    : Signal round-end (frontend triggers countdown)
- loop_submit : Record user input for the current round
- loop_next   : Advance to the next round
- loop_stop   : End the loop early and render summary

Cron-compatibility tools (daemon-driven, routed to LoopManager):
- cron_create : Create a non-interactive scheduled job
- cron_list   : List all loop/cron jobs
- cron_delete : Delete a loop/cron job by id
"""

from __future__ import annotations

import logging

from datetime import datetime

from croniter import croniter
from pydantic import BaseModel, Field

from loop_manager import (
    LoopManager,
    add as loop_add,
    add_interactive as loop_add_interactive,
    complete_job,
    delete as loop_delete,
    get as loop_get,
    get_active as loop_get_active,
    update_round as loop_update_round,
    update_status,
)
from loop_models import LoopStatus
from runtime_paths import context_runtime_data_dir
from tools.base import Context, Tool, ToolResult

logger = logging.getLogger(__name__)


def _loop_job_error(job_id: str, message: str | None = None) -> ToolResult:
    output = message or f"未找到 Loop 任务 [{job_id}]。"
    return ToolResult(
        output=output,
        metadata={
            "error": output,
            "error_type": "not_found",
            "job_id": job_id,
        },
    )


# ---------------------------------------------------------------------------
# Interactive Loop tools
# ---------------------------------------------------------------------------


class LoopStartInput(BaseModel):
    rounds: int = Field(ge=1, le=100, description="总轮数，例如 4 表示 4 轮番茄钟")
    duration_minutes: int = Field(
        ge=1, le=180, description="每轮时长（分钟），例如 25 表示 25 分钟专注"
    )
    user_intent: str = Field(
        description="用户原始意图描述，用于在总结和日记中保留上下文"
    )


class LoopStartTool(Tool):
    """Start an interactive loop session (round-based, frontend-driven).

    Writes a LoopJob(interactive=True) to the store, then the frontend begins
    the countdown. When each round ends, the LLM calls loop_ask to prompt the
    user. When all rounds finish, the LLM calls loop_stop to render a summary.
    """

    name = "loop_start"
    description = (
        "启动一个交互式 Loop 任务（番茄钟、轮次练习等）。"
        "由前端驱动倒计时，后端管理状态和轮次记录。"
        "适用于需要重复执行且每轮之间需要用户反馈的工作流。"
    )
    input_schema = LoopStartInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopStartInput)

        runtime_data_path = context_runtime_data_dir(ctx)

        # Check in-memory session first (authoritative for current process),
        # then fall back to disk for restart recovery.
        from memory import get_session_store
        store = get_session_store()
        existing_job_id: str | None = None
        if ctx.session_id and store is not None:
            session = store.get(ctx.session_id)
            if session is not None and session.active_loop_id:
                existing_job_id = session.active_loop_id
        if not existing_job_id:
            active_job = loop_get_active(
                ctx.session_id or "",
                runtime_data_path=runtime_data_path,
            )
            if active_job is not None:
                existing_job_id = active_job.id
        if existing_job_id is not None:
            return ToolResult(
                output=(
                    f"该会话已有一个进行中的 loop 任务 [{existing_job_id}]，"
                    "请先完成或停止后再开始新的。"
                ),
                metadata={"active_loop_id": existing_job_id},
            )

        job_id = loop_add_interactive(
            rounds=params.rounds,
            duration_minutes=params.duration_minutes,
            user_intent=params.user_intent,
            source_session_id=ctx.session_id or None,
            source_conversation_id=ctx.conversation_id or None,
            runtime_data_path=runtime_data_path,
        )

        # Update the session's active_loop_id for reliable WebSocket routing.
        if ctx.session_id:
            from memory import get_session_store
            store = get_session_store()
            if store is not None:
                session = store.get(ctx.session_id)
                if session is not None:
                    session.active_loop_id = job_id
                    store.persist(session)

        # Notify the frontend to begin the countdown timer.
        sent = False
        if ctx.session_id:
            from api.websocket import send_loop_event
            sent = await send_loop_event(ctx.session_id, {
                "type": "loop_start",
                "job_id": job_id,
                "rounds": params.rounds,
                "duration_minutes": params.duration_minutes,
                "user_intent": params.user_intent,
            })
            if not sent:
                logger.warning(
                    "send_loop_event failed for session %s — frontend not connected",
                    ctx.session_id,
                )

        return ToolResult(
            output=(
                f"Loop 任务已启动！\n"
                f"任务 ID: {job_id}\n"
                f"轮数: {params.rounds} 轮 | 每轮: {params.duration_minutes} 分钟\n"
                f"前端已收到启动信号，开始倒计时。"
                if sent
                else (
                    f"Loop 任务已创建，但前端未连接，无法启动倒计时。\n"
                    f"任务 ID: {job_id}\n"
                    f"轮数: {params.rounds} 轮 | 每轮: {params.duration_minutes} 分钟"
                )
            ),
            metadata={
                "job_id": job_id,
                "rounds": params.rounds,
                "duration_minutes": params.duration_minutes,
            },
        )


class LoopAskInput(BaseModel):
    job_id: str = Field(description="当前 loop 任务的 ID")
    round_note: str = Field(
        default="",
        description="可选的轮次备注（例如本轮表现、遇到的问题）",
    )


class LoopAskTool(Tool):
    """Signal that the current round has ended and prompt the user for input.

    Marks the job as waiting, sends a loop_ask event to the frontend so it
    displays an input field. The frontend will send loop_submit when done.
    """

    name = "loop_ask"
    description = (
        "通知前端当前轮次结束，请用户输入本轮的感受或回答。"
        "调用后 Loop 状态变为 waiting，前端会显示输入框等待用户提交。"
    )
    input_schema = LoopAskInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopAskInput)
        runtime_data_path = context_runtime_data_dir(ctx)

        job = loop_get(params.job_id, runtime_data_path=runtime_data_path)
        if job is None:
            return _loop_job_error(params.job_id)
        if not job.interactive:
            return ToolResult(output="loop_ask 仅适用于交互式 loop 任务。")

        update_status(params.job_id, LoopStatus.WAITING, runtime_data_path=runtime_data_path)

        # Notify the frontend to show the round-end input dialog.
        target_session = job.source_session_id or ctx.session_id or ""
        frontend_connected = False
        if target_session:
            from api.websocket import send_loop_event
            frontend_connected = await send_loop_event(target_session, {
                "type": "loop_ask",
                "job_id": job.id,
                "current_round": job.current_round,
                "total_rounds": job.rounds or 0,
                "round_note": params.round_note,
            })

        return ToolResult(
            output=(
                f"第 {job.current_round}/{job.rounds} 轮结束。\n"
                + (f"备注: {params.round_note}\n" if params.round_note else "")
                + ("已通知前端显示输入框，等待用户提交。" if frontend_connected
                   else "已切换到等待状态（前端未连接，输入框可能不会自动显示）。")
            ),
            metadata={
                "job_id": job.id,
                "current_round": job.current_round,
                "total_rounds": job.rounds,
            },
        )


class LoopSubmitInput(BaseModel):
    job_id: str = Field(description="当前 loop 任务的 ID")
    user_input: str = Field(description="用户对本轮询问的输入内容")


class LoopSubmitTool(Tool):
    """Record the user's response to the current round's question.

    Updates the job with the user's input and advances the round counter.
    If this was the last round, the status becomes DONE.
    """

    name = "loop_submit"
    description = (
        "记录用户对当前轮次询问的回答，并推进到下一轮。"
        "如果所有轮次已完成，Loop 进入 DONE 状态，可调用 loop_stop 渲染总结。"
    )
    input_schema = LoopSubmitInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopSubmitInput)
        runtime_data_path = context_runtime_data_dir(ctx)

        job = loop_update_round(
            params.job_id,
            response={"user_input": params.user_input},
            runtime_data_path=runtime_data_path,
        )

        if job is None:
            return _loop_job_error(
                params.job_id,
                f"未找到或无法更新 Loop 任务 [{params.job_id}]。",
            )

        # Clear active_loop_id from session when the loop reaches DONE.
        if job.status == LoopStatus.DONE and job.source_session_id:
            from memory import get_session_store
            store = get_session_store()
            if store is not None:
                s = store.get(job.source_session_id)
                if s is not None and s.active_loop_id == job.id:
                    s.active_loop_id = None
                    store.persist(s)
            return ToolResult(
                output=(
                    f"第 {job.current_round - 1} 轮回答已记录。\n"
                    "所有轮次已完成！请调用 loop_stop 渲染总结和日记。"
                ),
                metadata={
                    "job_id": job.id,
                    "all_rounds_complete": True,
                    "current_round": job.current_round,
                },
            )

        return ToolResult(
            output=(
                f"第 {job.current_round - 1}/{job.rounds} 轮回答已记录。"
                f"\n下一轮（第 {job.current_round}/{job.rounds} 轮）已开始。"
            ),
            metadata={
                "job_id": job.id,
                "all_rounds_complete": False,
                "next_round": job.current_round,
                "total_rounds": job.rounds,
            },
        )


class LoopNextInput(BaseModel):
    job_id: str = Field(description="当前 loop 任务的 ID")
    start_immediately: bool = Field(
        default=True,
        description="是否立即开始下一轮倒计时",
    )


class LoopNextTool(Tool):
    """Advance to the next round (for use after a round ends without user input)."""

    name = "loop_next"
    description = (
        "直接进入下一轮，不等待用户额外输入。适用于轮次间无需用户反馈的情况。"
        "会重置 Loop 状态为 ACTIVE，前端开始下一轮倒计时。"
    )
    input_schema = LoopNextInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopNextInput)
        runtime_data_path = context_runtime_data_dir(ctx)

        job = loop_get(params.job_id, runtime_data_path=runtime_data_path)
        if job is None:
            return _loop_job_error(params.job_id)

        updated = loop_update_round(
            params.job_id,
            response={},
            runtime_data_path=runtime_data_path,
        )
        if updated is None:
            return _loop_job_error(
                params.job_id,
                f"未找到或无法更新 Loop 任务 [{params.job_id}]。",
            )

        # Clear active_loop_id from session when the loop reaches DONE.
        if updated.status == LoopStatus.DONE and updated.source_session_id:
            from memory import get_session_store
            store = get_session_store()
            if store is not None:
                s = store.get(updated.source_session_id)
                if s is not None and s.active_loop_id == updated.id:
                    s.active_loop_id = None
                    store.persist(s)

        target_session = job.source_session_id or ctx.session_id or ""
        sent = False
        if target_session:
            from api.websocket import send_loop_event
            sent = await send_loop_event(target_session, {
                "type": "loop_next",
                "job_id": updated.id,
                "current_round": updated.current_round,
                "total_rounds": updated.rounds or 0,
                "duration_minutes": updated.duration_minutes or 0,
            })
            if not sent:
                logger.warning(
                    "send_loop_event failed for session %s — frontend not connected",
                    target_session,
                )

        return ToolResult(
            output=(
                f"已进入第 {updated.current_round}/{updated.rounds} 轮。"
                + ("（最后一轮）" if updated.status == LoopStatus.DONE else "")
            ),
            metadata={
                "job_id": updated.id,
                "current_round": updated.current_round,
                "total_rounds": updated.rounds,
                "done": updated.status == LoopStatus.DONE,
            },
        )


class LoopPauseInput(BaseModel):
    job_id: str = Field(description="要暂停的 loop 任务的 ID")


class LoopPauseTool(Tool):
    """Pause an active interactive loop."""

    name = "loop_pause"
    description = (
        "暂停一个进行中的交互式 Loop 任务。"
        "将状态改为 paused，前端停止倒计时。"
    )
    input_schema = LoopPauseInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopPauseInput)
        runtime_data_path = context_runtime_data_dir(ctx)

        job = loop_get(params.job_id, runtime_data_path=runtime_data_path)
        if job is None:
            return _loop_job_error(params.job_id)

        update_status(params.job_id, LoopStatus.PAUSED, runtime_data_path=runtime_data_path)

        # Sync session's active_loop_id so LoopStartTool can detect a paused loop
        # and reject creating a duplicate instead of orphaning the paused one.
        if job.source_session_id:
            from memory import get_session_store

            store = get_session_store()
            if store is not None:
                s = store.get(job.source_session_id)
                if s is not None and s.active_loop_id == job.id:
                    # Keep active_loop_id set — the loop is still active (just paused).
                    store.persist(s)

        target_session = job.source_session_id or ctx.session_id or ""
        sent = False
        if target_session:
            from api.websocket import send_loop_event
            sent = await send_loop_event(target_session, {
                "type": "loop_paused",
                "job_id": job.id,
            })
            if not sent:
                logger.warning(
                    "send_loop_event failed for session %s — frontend not connected",
                    target_session,
                )

        return ToolResult(
            output=f"Loop 任务 [{job.id}] 已暂停。",
            metadata={"job_id": job.id, "status": "paused"},
        )


class LoopStopInput(BaseModel):
    job_id: str = Field(description="要结束的 loop 任务的 ID")


class LoopStopTool(Tool):
    """Stop a loop and render a summary journal entry."""

    name = "loop_stop"
    description = (
        "主动结束一个 Loop 任务（可提前终止或正常完成所有轮次后结束）。"
        "渲染总结和日记，然后从队列中移除该任务。"
    )
    input_schema = LoopStopInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, LoopStopInput)
        runtime_data_path = context_runtime_data_dir(ctx)

        job = loop_get(params.job_id, runtime_data_path=runtime_data_path)
        if job is None:
            return _loop_job_error(params.job_id)

        complete_job(params.job_id, runtime_data_path=runtime_data_path)

        # Clear the session's active_loop_id.
        if job.source_session_id:
            from memory import get_session_store
            store = get_session_store()
            if store is not None:
                session = store.get(job.source_session_id)
                if session is not None and session.active_loop_id == params.job_id:
                    session.active_loop_id = None
                    store.persist(session)

        # Render a summary from round responses
        lines = [
            f"# Loop 总结 — {job.user_intent}",
            "",
            f"**总轮数**: {job.rounds} 轮 | **每轮时长**: {job.duration_minutes} 分钟",
            f"**完成轮数**: {len(job.round_responses)} 轮",
            f"**开始时间**: {job.created_at}",
            f"**结束时间**: {datetime.now().isoformat()}",
            "",
            "## 各轮记录",
        ]
        for r in job.round_responses:
            lines.append(f"\n### 第 {r['round']} 轮")
            resp = r.get("response", {})
            lines.append(f"- 用户输入: {resp.get('user_input', '(无)')}")
            lines.append(f"- 记录时间: {r.get('recorded_at', '?')}")

        if not job.round_responses:
            lines.append("\n*（本轮无用户输入记录）*")

        summary = "\n".join(lines)

        # Notify the frontend that the loop has ended.
        target_session = job.source_session_id or ctx.session_id or ""
        if target_session:
            from api.websocket import send_loop_event
            sent = await send_loop_event(target_session, {
                "type": "loop_ended",
                "job_id": job.id,
                "rounds_completed": len(job.round_responses),
            })
            if not sent:
                logger.warning(
                    "send_loop_event failed for session %s — frontend not connected",
                    target_session,
                )

        return ToolResult(
            output=summary,
            metadata={
                "job_id": job.id,
                "rounds_completed": len(job.round_responses),
            },
        )


# ---------------------------------------------------------------------------
# Cron-compatibility tools (routed to LoopManager)
# ---------------------------------------------------------------------------


class CronCreateInput(BaseModel):
    cron: str = Field(
        description=(
            "标准 5 字段 Cron 表达式，或秒在前的 6 字段表达式；"
            '例如 "*/5 * * * *" 表示每 5 分钟，'
            '"*/10 * * * * *" 表示每 10 秒。'
        )
    )
    prompt: str = Field(description="当触发时赋予你的任务指令或系统提示。")
    recurring: bool = Field(
        default=True,
        description="是否为循环任务。如果为 false，则执行一次即销毁。",
    )


class CronCreateTool(Tool):
    """Create a non-interactive scheduled job (routed to LoopManager)."""

    name = "cron_create"
    description = (
        "为系统设定一个定时的预约任务或循环检查计划。"
        "通过设置标准 Cron 表达式，系统会在满足触发时间时唤醒并执行任务。"
        "适用于定期归档、检查更新或日志汇报等不需要用户参与的任务。"
    )
    input_schema = CronCreateInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, CronCreateInput)
        fields_count = len(params.cron.strip().split())
        if fields_count not in (5, 6) or not croniter.is_valid(
            params.cron,
            second_at_beginning=fields_count == 6,
        ):
            return ToolResult(
                output=f"格式错误：'{params.cron}' 不是有效的 Cron 表达式。"
            )

        runtime_data_path = context_runtime_data_dir(ctx)
        job_id = loop_add(
            params.cron,
            params.prompt,
            params.recurring,
            source_session_id=ctx.session_id or None,
            source_conversation_id=ctx.conversation_id or None,
            runtime_data_path=runtime_data_path,
        )
        kind = "循环" if params.recurring else "单次"
        return ToolResult(
            output=(
                f"成功创建{kind}定时任务！\n"
                f"任务 ID: {job_id}\n"
                f"时间规则: {params.cron}\n"
                "系统将在后台自动追踪并在就绪时唤醒你。"
            ),
            metadata={"job_id": job_id},
        )


class CronListInput(BaseModel):
    pass


class CronListTool(Tool):
    """List all loop and cron jobs (routed to LoopManager)."""

    name = "cron_list"
    description = "列出当前系统中所有定时作业和 Loop 任务及其详细信息。"
    input_schema = CronListInput
    is_read_only = True

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        runtime_data_path = context_runtime_data_dir(ctx)
        jobs = LoopManager.load(runtime_data_path)
        if not jobs:
            return ToolResult(output="当前系统没有设置任何定时任务或 Loop。")

        lines = []
        for j in jobs:
            src = j.source_session_id or "(未知)"
            if j.interactive:
                lines.append(
                    f"- ID: `{j.id}` | 类型: interactive | "
                    f"轮数: {j.rounds}×{j.duration_minutes}min | "
                    f"状态: {j.status.value} | 来源: {src}\n"
                    f"  意图: {j.user_intent}"
                )
            else:
                lines.append(
                    f"- ID: `{j.id}` | 类型: cron | 规则: `{j.cron}` | "
                    f"循环: {j.recurring} | 来源: {src}\n"
                    f"  任务: {j.prompt}"
                )
        return ToolResult(output="\n".join(lines))


class CronDeleteInput(BaseModel):
    job_id: str = Field(
        description="要删除或取消的定时任务 / Loop 的唯一 ID（例如 loop_a1b2c3d4）"
    )


class CronDeleteTool(Tool):
    """Delete a loop or cron job by id (routed to LoopManager)."""

    name = "cron_delete"
    description = "删除或取消一个已规划好的 Loop 任务或定时任务。"
    input_schema = CronDeleteInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, CronDeleteInput)
        runtime_data_path = context_runtime_data_dir(ctx)
        success = loop_delete(params.job_id, runtime_data_path=runtime_data_path)
        if success:
            return ToolResult(
                output=f"任务 {params.job_id} 已从追踪列表移除，将被停止调度。"
            )
        return ToolResult(
            output=f"错误: 找不到 ID 为 {params.job_id} 的任务。"
        )
