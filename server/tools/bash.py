"""Cross-platform non-interactive shell execution tool."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import signal
import subprocess
import sys

from pydantic import BaseModel, Field

from runtime_paths import tool_results_cache_dir
from tools.base import Context, Tool, ToolResult

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

DEFAULT_BASH_TIMEOUT = int(os.getenv("CRABBY_BASH_TIMEOUT", "1800"))


def _detect_shell() -> str:
    """Return the preferred shell for the current platform.

    macOS 10.15+ defaults to zsh; use it directly to avoid ambiguous bash/zsh
    resolution on those systems. Linux and other Unix platforms use bash.
    """
    if IS_MAC:
        return "/bin/zsh"
    return "/bin/bash"

WINDOWS_UTF8_PREAMBLE = (
    "[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$OutputEncoding = [System.Text.Encoding]::UTF8; "
)
WINDOWS_CHAIN_FAILURE_EXIT = (
    "if ($global:LASTEXITCODE -is [int] -and $global:LASTEXITCODE -ne 0) "
    "{ exit $global:LASTEXITCODE } else { exit 1 }"
)

BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(^|\s)rm(\s|$)", re.IGNORECASE),
    re.compile(r"\brmdir\b", re.IGNORECASE),
    re.compile(r"\bunlink\b", re.IGNORECASE),
    re.compile(r"\bshred\b", re.IGNORECASE),
    re.compile(r"\bdel\b", re.IGNORECASE),
    re.compile(r"\berase\b", re.IGNORECASE),
    re.compile(r"\brd\b\s+/s", re.IGNORECASE),
    re.compile(r"\brmdir\b\s+/s", re.IGNORECASE),
    re.compile(r"\bremove-item\b", re.IGNORECASE),
    re.compile(r"(^|\s)ri(\s|$)", re.IGNORECASE),
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    re.compile(r"\bmkfs\.", re.IGNORECASE),
    re.compile(r"\bdd\s+if=.*of=/dev", re.IGNORECASE),
    re.compile(r">\s*/dev/sd", re.IGNORECASE),
    re.compile(r"find\s+.*-delete", re.IGNORECASE),
    re.compile(r"find\s+.*-exec\s+rm", re.IGNORECASE),
]

DANGEROUS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b", re.IGNORECASE), "警告：命令包含 sudo，可能需要人工确认。"),
    (
        re.compile(r"\bpip(?:3)?\s+install\b", re.IGNORECASE),
        "警告：这会修改 Python 环境，请确认这是你想要的。",
    ),
    (
        re.compile(r"\bchmod\s+777\b", re.IGNORECASE),
        "警告：chmod 777 会放开全部权限。",
    ),
]


def _check_blocked_command(command: str) -> str | None:
    for pattern in BLOCKED_PATTERNS:
        if pattern.search(command):
            return f"命令被拒绝：检测到禁止的破坏性操作 ({pattern.pattern})。"
    return None


def _check_dangerous_command(command: str) -> list[str]:
    return [message for pattern, message in DANGEROUS_PATTERNS if pattern.search(command)]


def _split_windows_chain(command: str) -> tuple[list[str], list[str]] | None:
    """Split top-level PowerShell command chains using && or ||.

    Windows PowerShell 5.x does not support these operators, but models often
    emit them from bash/cmd habit. Keep this intentionally small: only split
    unquoted operators and leave malformed commands unchanged.
    """
    segments: list[str] = []
    operators: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0

    while i < len(command):
        ch = command[i]

        if ch == "`":
            buf.append(ch)
            if i + 1 < len(command):
                i += 1
                buf.append(command[i])
            i += 1
            continue

        if quote == "'":
            buf.append(ch)
            if ch == "'":
                if i + 1 < len(command) and command[i + 1] == "'":
                    i += 1
                    buf.append(command[i])
                else:
                    quote = None
            i += 1
            continue

        if quote == '"':
            buf.append(ch)
            if ch == '"':
                quote = None
            i += 1
            continue

        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            i += 1
            continue

        operator = command[i : i + 2]
        if operator in {"&&", "||"}:
            segment = "".join(buf).strip()
            if not segment:
                return None
            segments.append(segment)
            operators.append(operator)
            buf = []
            i += 2
            continue

        buf.append(ch)
        i += 1

    final_segment = "".join(buf).strip()
    if not final_segment or not operators:
        return None

    segments.append(final_segment)
    return segments, operators


def _build_windows_script(command: str) -> str:
    chain = _split_windows_chain(command)
    if chain is None:
        return f"{WINDOWS_UTF8_PREAMBLE}{command}"

    segments, operators = chain
    lines = [
        "$__lifeAssistantOk = $true",
        segments[0],
        "$__lifeAssistantOk = $?",
    ]
    for operator, segment in zip(operators, segments[1:]):
        condition = "$__lifeAssistantOk" if operator == "&&" else "-not $__lifeAssistantOk"
        lines.append(
            f"if ({condition}) {{ {segment}; $__lifeAssistantOk = $? }}",
        )
    lines.append(
        f"if (-not $__lifeAssistantOk) {{ {WINDOWS_CHAIN_FAILURE_EXIT} }}",
    )
    return f"{WINDOWS_UTF8_PREAMBLE}{'; '.join(lines)}"


def _build_shell_command(command: str) -> list[str]:
    if IS_WINDOWS:
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _build_windows_script(command),
        ]
    shell = _detect_shell()
    return [shell, "-c", command]


def _clean_env_vars() -> dict[str, str]:
    env = os.environ.copy()
    sensitive_markers = ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL")
    for key in list(env.keys()):
        upper_key = key.upper()
        if any(marker in upper_key for marker in sensitive_markers):
            env.pop(key, None)
    return env


def _kill_process_tree(pid: int) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
                capture_output=True,
            )
        elif IS_MAC:
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGKILL)
    except Exception as exc:  # pragma: no cover - best effort cleanup
        logger.warning("Failed to kill process tree %s: %s", pid, exc)


async def _read_stream_to_end(stream: asyncio.StreamReader | None) -> bytes:
    if stream is None:
        return b""

    chunks: list[bytes] = []
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        chunks.append(chunk)

    return b"".join(chunks)


async def _run_background_task(
    process: asyncio.subprocess.Process,
    command: str,
    session_id: str | None,
) -> None:
    if not session_id:
        return

    from api.websocket import push_notification

    timeout_seconds = DEFAULT_BASH_TIMEOUT
    timed_out = False
    exit_code = -1

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_seconds,
        )
        exit_code = process.returncode or 0
    except asyncio.TimeoutError:
        timed_out = True
        _kill_process_tree(process.pid)
        await process.wait()
        stdout_bytes = await _read_stream_to_end(process.stdout)
        stderr_bytes = await _read_stream_to_end(process.stderr)
    except Exception as exc:  # pragma: no cover - notification best effort
        logger.exception("Background bash task failed: %s", exc)
        stdout_bytes = b""
        stderr_bytes = str(exc).encode("utf-8", errors="replace")

    lines = [f"Background Task Finished (PID: {process.pid})", f"Command: {command}"]
    if timed_out:
        lines.append(f"Status: timed out after {timeout_seconds}s")
    else:
        lines.append(f"Exit Code: {exit_code}")

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    if stdout:
        lines.append(f"== STDOUT ==\n{stdout}")
    if stderr:
        lines.append(f"== STDERR ==\n{stderr}")

    try:
        await push_notification(session_id, "\n".join(lines))
    except Exception as exc:  # pragma: no cover - notification best effort
        logger.warning("Failed to push background bash notification: %s", exc)


class BashInput(BaseModel):
    command: str = Field(description="要执行的 shell 命令。")
    timeout: int = Field(
        default=120,
        ge=1,
        le=600,
        description="前台命令超时秒数。",
    )
    is_background: bool = Field(
        default=False,
        description="是否以后台任务方式启动。",
    )


class BashTool(Tool):
    name = "bash"
    description = (
        "执行跨平台、非交互式 shell 命令（Windows 用 PowerShell，macOS 用 zsh，"
        "Linux 用 bash）。该工具没有 TTY，不适合需要人工输入的命令。"
    )
    input_schema = BashInput
    is_read_only = False
    max_result_chars = 30_000

    def _check_blocked(self, command: str) -> str | None:
        return _check_blocked_command(command)

    def _check_dangerous(self, command: str) -> list[str]:
        return _check_dangerous_command(command)

    def _clean_env(self) -> dict[str, str]:
        return _clean_env_vars()

    def check_permission(self, params: BaseModel, ctx: Context) -> bool:
        return ctx.permission_level != "restricted"

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        assert isinstance(params, BashInput)

        command = params.command.strip()
        if not command:
            return ToolResult(
                output="错误：命令不能为空。",
                metadata={"exit_code": None},
            )

        blocked_reason = self._check_blocked(command)
        if blocked_reason:
            return ToolResult(
                output=blocked_reason,
                metadata={"blocked": True, "exit_code": None},
            )

        warnings = self._check_dangerous(command)
        shell_args = _build_shell_command(command)

        try:
            process = await asyncio.create_subprocess_exec(
                *shell_args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ctx.vault_path),
                env=self._clean_env(),
            )
        except OSError as exc:
            return ToolResult(
                output=f"无法启动进程：{exc}",
                metadata={"exit_code": None},
            )

        if params.is_background:
            asyncio.create_task(
                _run_background_task(process, command, ctx.session_id),
            )
            return ToolResult(
                output=f"后台命令已启动，PID: {process.pid}",
                metadata={
                    "background": True,
                    "pid": process.pid,
                    "exit_code": None,
                },
            )

        timeout_occurred = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=params.timeout,
            )
            exit_code = process.returncode or 0
        except asyncio.TimeoutError:
            timeout_occurred = True
            _kill_process_tree(process.pid)
            await process.wait()
            stdout_bytes = await _read_stream_to_end(process.stdout)
            stderr_bytes = await _read_stream_to_end(process.stderr)
            exit_code = -1

        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()

        parts: list[str] = []
        if warnings:
            parts.extend(warnings)

        if timeout_occurred:
            parts.append(
                f"超时：命令执行超过 {params.timeout}s，已被系统终止。",
            )
        elif exit_code != 0:
            parts.append(f"[退出码: {exit_code}]")

        if stdout:
            parts.append(stdout)
        if stderr:
            parts.append(f"[stderr]\n{stderr}")

        output = "\n".join(parts).strip() or "(命令执行完成，无输出)"
        is_truncated = False
        cache_path = None
        if len(output) > self.max_result_chars:
            cache_dir = tool_results_cache_dir(ctx)
            cache_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(output.encode("utf-8")).hexdigest()[:12]
            cache_file = cache_dir / f"bash-{digest}.txt"
            cache_file.write_text(output, encoding="utf-8")
            cache_path = str(cache_file)
            output = output[: self.max_result_chars]
            is_truncated = True

        return ToolResult(
            output=output,
            metadata={
                "exit_code": exit_code,
                "timeout": timeout_occurred,
                "warnings": warnings,
            },
            is_truncated=is_truncated,
            cache_path=cache_path,
        )
