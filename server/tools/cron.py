"""Schedule cron tool — 创建和管理定时唤醒任务。

允许大模型像设置闹钟一样安排长期定时任务。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from croniter import croniter
from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult

CRABBY_VAULT_DIR = ".Crabby"
LEGACY_CRABBY_VAULT_DIR = ".LifeAssistantAgent"


class CronJob(BaseModel):
    id: str
    cron: str
    prompt: str
    recurring: bool
    created_at: str
    source_session_id: str | None = None
    """创建该任务时所在的会话 ID。触发结果会推送回该来源会话。"""
    last_fired_at: str | None = None
    """上次触发的 ISO 时间戳 (防同一分钟重复触发)。"""


class CronManager:
    """负责管理 Vault 内的 .Crabby/data/cron_jobs.json"""

    @classmethod
    def get_file(cls, vault_path: Path) -> Path:
        file_path = vault_path / CRABBY_VAULT_DIR / "data" / "cron_jobs.json"
        legacy_path = vault_path / LEGACY_CRABBY_VAULT_DIR / "data" / "cron_jobs.json"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if not file_path.exists() and legacy_path.exists():
            file_path.write_bytes(legacy_path.read_bytes())
        return file_path

    @classmethod
    def load(cls, vault_path: Path) -> list[CronJob]:
        file_path = cls.get_file(vault_path)
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text("utf-8"))
            return [CronJob(**d) for d in data]
        except Exception:
            return []

    @classmethod
    def save(cls, vault_path: Path, jobs: list[CronJob]) -> None:
        file_path = cls.get_file(vault_path)
        data = [j.model_dump() for j in jobs]
        file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")

    @classmethod
    def add(
        cls,
        vault_path: Path,
        cron: str,
        prompt: str,
        recurring: bool,
        source_session_id: str | None = None,
    ) -> str:
        jobs = cls.load(vault_path)
        job_id = f"cron_{uuid.uuid4().hex[:8]}"
        job = CronJob(
            id=job_id,
            cron=cron,
            prompt=prompt,
            recurring=recurring,
            created_at=datetime.now().isoformat(),
            source_session_id=source_session_id,
        )
        jobs.append(job)
        cls.save(vault_path, jobs)
        return job_id

    @classmethod
    def delete(cls, vault_path: Path, job_id: str) -> bool:
        jobs = cls.load(vault_path)
        new_jobs = [j for j in jobs if j.id != job_id]
        if len(new_jobs) == len(jobs):
            return False
        cls.save(vault_path, new_jobs)
        return True

    @classmethod
    def update_last_fired(cls, vault_path: Path, job_id: str, *, clear: bool = False) -> None:
        """更新指定 job 的 last_fired_at。

        Args:
            clear: 若为 True，清除 last_fired_at（允许重新触发，用于单次任务失败重试）。
        """
        jobs = cls.load(vault_path)
        for j in jobs:
            if j.id == job_id:
                j.last_fired_at = None if clear else datetime.now().isoformat()
                break
        cls.save(vault_path, jobs)


class CronCreateInput(BaseModel):
    cron: str = Field(
        description=(
            '标准 5 字段 Cron 表达式，或秒在前的 6 字段表达式；'
            '例如 "*/5 * * * *" 表示每 5 分钟，'
            '"*/10 * * * * *" 表示每 10 秒。'
        )
    )
    prompt: str = Field(description='当触发时，赋予你的任务指令或系统提示。')
    recurring: bool = Field(default=True, description='是否为循环任务。如果为 false，则执行一次即销毁。')


class CronCreateTool(Tool):
    name = "cron_create"
    description = (
        "为系统设定一个定时的预约任务或循环检查计划。通过设置一个标准的 Cron 表达式，"
        "系统会在满足触发时间时，唤醒并把 prompt 塞进你的思考上下文中以启动对应任务（例如用来定期执行归档、检查更新或日志汇报）。"
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
            return ToolResult(output=f"格式错误：'{params.cron}' 不是有效的 Cron 表达式。")

        job_id = CronManager.add(
            ctx.vault_path,
            params.cron,
            params.prompt,
            params.recurring,
            source_session_id=ctx.session_id or ctx.conversation_id,
        )
        kind = "循环" if params.recurring else "单次"
        return ToolResult(
            output=f"成功创建{kind}定时任务！\n任务 ID: {job_id}\n时间规则: {params.cron}\n系统将在后台自动追踪并在就绪时唤醒你。",
            metadata={"job_id": job_id},
        )


class CronListInput(BaseModel):
    pass


class CronListTool(Tool):
    name = "cron_list"
    description = "列出当前系统中已经挂载的所有定时作业及其 ID 等详细信息。"
    input_schema = CronListInput
    is_read_only = True

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        jobs = CronManager.load(ctx.vault_path)
        if not jobs:
            return ToolResult(output="当前系统没有设置任何有效的定时任务。")

        lines = []
        for j in jobs:
            src = j.source_session_id or "(未知)"
            lines.append(
                f"- ID: `{j.id}` | 规则: `{j.cron}` | 循环: {j.recurring} | 来源会话: {src}\n  任务: {j.prompt}"
            )
        return ToolResult(output="\n".join(lines))


class CronDeleteInput(BaseModel):
    job_id: str = Field(description="你需要删除或取消的定时任务的唯一 ID (例如 cron_a1b2c3d4)")


class CronDeleteTool(Tool):
    name = "cron_delete"
    description = "删除/取消一个已规划好的定时任务。"
    input_schema = CronDeleteInput
    is_read_only = False

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, CronDeleteInput)
        success = CronManager.delete(ctx.vault_path, params.job_id)
        if success:
            return ToolResult(output=f"任务 {params.job_id} 已从追踪列表移除，将被停止调度。")
        else:
            return ToolResult(output=f"错误: 找不到 ID 为 {params.job_id} 的任务。")
