"""BashTool 单元测试。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import tools.bash as bash_module
from api import websocket as websocket_api
from llm.tool_executor import execute_tool_call
from tools.base import Context
from tools.bash import BashTool
from tools.registry import ToolRegistry


@pytest.fixture
def tool():
    return BashTool()


@pytest.fixture
def ctx(tmp_path: Path):
    return Context(vault_path=tmp_path)


# -- 安全检查 ----------------------------------------------------------------


class TestBlockedCommands:
    """黑名单拦截测试 — 所有删除类和破坏性命令必须被拒绝。"""

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf /",
            "rm -rf ~",
            "rm file.txt",
            "rm -r some_dir",
            "rmdir some_dir",
            "unlink file.txt",
            "shred file.txt",
            "find . -delete",
            "find . -exec rm {} +",
        ],
    )
    def test_unix_delete_blocked(self, tool: BashTool, command: str):
        result = tool._check_blocked(command)
        assert result is not None, f"Should block: {command}"

    @pytest.mark.parametrize(
        "command",
        [
            "del file.txt",
            "erase file.txt",
            "rd /s folder",
            "rmdir /s folder",
            "Remove-Item file.txt",
            "ri file.txt",
        ],
    )
    def test_windows_delete_blocked(self, tool: BashTool, command: str):
        result = tool._check_blocked(command)
        assert result is not None, f"Should block: {command}"

    @pytest.mark.parametrize(
        "command",
        [
            "format C:",
            "mkfs.ext4 /dev/sda1",
            "dd if=/dev/zero of=/dev/sda",
            "> /dev/sda",
        ],
    )
    def test_destructive_blocked(self, tool: BashTool, command: str):
        result = tool._check_blocked(command)
        assert result is not None, f"Should block: {command}"

    @pytest.mark.parametrize(
        "command",
        [
            "echo hello",
            "ls -la",
            "cat file.txt",
            "git status",
            "python --version",
            "pwd",
            "dir",
            "Get-ChildItem",
        ],
    )
    def test_safe_commands_allowed(self, tool: BashTool, command: str):
        result = tool._check_blocked(command)
        assert result is None, f"Should allow: {command}"


class TestDangerousPatterns:
    """危险模式检测 — 发出警告但不阻止。"""

    def test_sudo_warning(self, tool: BashTool):
        warnings = tool._check_dangerous("sudo apt install vim")
        assert any("sudo" in w for w in warnings)

    def test_pip_install_warning(self, tool: BashTool):
        warnings = tool._check_dangerous("pip install requests")
        assert any("Python" in w for w in warnings)

    def test_safe_no_warning(self, tool: BashTool):
        warnings = tool._check_dangerous("echo hello")
        assert len(warnings) == 0


# -- 命令执行 ----------------------------------------------------------------


class TestCommandExecution:
    """实际命令执行测试。"""

    @pytest.mark.asyncio
    async def test_simple_echo(self, tool: BashTool, ctx: Context):
        """测试简单的 echo 命令。"""
        if sys.platform == "win32":
            cmd = "echo 'hello world'"
        else:
            cmd = "echo hello world"
        result = await tool.call(
            tool.input_schema(command=cmd),
            ctx,
        )
        assert "hello" in result.output
        assert result.metadata["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_empty_command_rejected(self, tool: BashTool, ctx: Context):
        result = await tool.call(
            tool.input_schema(command=""),
            ctx,
        )
        assert "空" in result.output

    @pytest.mark.asyncio
    async def test_blocked_command_returns_error(self, tool: BashTool, ctx: Context):
        """被禁止的命令应该返回错误而不是执行。"""
        result = await tool.call(
            tool.input_schema(command="rm -rf /tmp/test"),
            ctx,
        )
        assert "拒绝" in result.output or "禁止" in result.output
        assert result.metadata.get("blocked") is True

    @pytest.mark.asyncio
    async def test_nonexistent_command_error(self, tool: BashTool, ctx: Context):
        """不存在的命令应该返回错误（非零退出码）。"""
        result = await tool.call(
            tool.input_schema(command="this_command_does_not_exist_xyz_123"),
            ctx,
        )
        # 应该有 stderr 输出或非零退出码
        assert (
            result.metadata.get("exit_code", 0) != 0
            or "stderr" in result.output.lower()
            or "not" in result.output.lower()
            or "无法" in result.output.lower()
        )

    @pytest.mark.asyncio
    async def test_execute_payload_marks_nonzero_exit_as_error(self, ctx: Context):
        registry = ToolRegistry()
        registry.register(BashTool())
        command = (
            "Write-Error 'visible failure'; exit 7"
            if sys.platform == "win32"
            else "printf 'visible failure' >&2; exit 7"
        )

        _llm_text, ui_payload = await execute_tool_call(
            registry,
            "bash",
            {"command": command},
            ctx=ctx,
            tool_id="toolu_fail",
        )

        assert ui_payload["id"] == "toolu_fail"
        assert ui_payload["name"] == "bash"
        assert ui_payload["status"] == "error"
        assert ui_payload["is_error"] is True
        assert ui_payload["metadata"]["exit_code"] == 7
        assert "visible failure" in ui_payload["output"]

    @pytest.mark.asyncio
    async def test_execute_payload_marks_blocked_command_as_error(self, ctx: Context):
        registry = ToolRegistry()
        registry.register(BashTool())

        _llm_text, ui_payload = await execute_tool_call(
            registry,
            "bash",
            {"command": "rm -rf /tmp/test"},
            ctx=ctx,
            tool_id="toolu_blocked",
        )

        assert ui_payload["id"] == "toolu_blocked"
        assert ui_payload["status"] == "error"
        assert ui_payload["is_error"] is True
        assert ui_payload["metadata"]["blocked"] is True

    @pytest.mark.asyncio
    async def test_timeout(self, tool: BashTool, ctx: Context):
        """超时测试 — 命令在超时后应该被终止。"""
        if sys.platform == "win32":
            cmd = "powershell -Command Start-Sleep -Seconds 10"
        else:
            cmd = "sleep 10"

        result = await tool.call(
            tool.input_schema(command=cmd, timeout=1),
            ctx,
        )
        assert "超时" in result.output
        assert result.metadata.get("timeout") is True

    @pytest.mark.asyncio
    async def test_working_directory(self, tool: BashTool, ctx: Context):
        """工作目录应该是 vault_path。"""
        if sys.platform == "win32":
            cmd = "Get-Location | Select-Object -ExpandProperty Path"
        else:
            cmd = "pwd"

        result = await tool.call(
            tool.input_schema(command=cmd),
            ctx,
        )
        # 输出应包含 vault_path（tmp_path 在 Windows 上可能是短路径）
        output = result.output.strip()
        vault_str = str(ctx.vault_path)
        assert (
            vault_str in output
            or ctx.vault_path.name in output
            or output in vault_str  # 短路径匹配
        ), f"Expected vault_path in output. output={output!r}, vault={vault_str!r}"

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
    async def test_windows_and_operator_chain(self, tool: BashTool, ctx: Context):
        result = await tool.call(
            tool.input_schema(command="Write-Output first && Write-Output second"),
            ctx,
        )

        assert "first" in result.output
        assert "second" in result.output
        assert result.metadata["exit_code"] == 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
    async def test_windows_and_operator_short_circuits_on_failure(
        self,
        tool: BashTool,
        ctx: Context,
    ):
        result = await tool.call(
            tool.input_schema(
                command='Set-Location "Z:\\life-assistant-missing-folder" && Write-Output should-not-run',
            ),
            ctx,
        )

        assert "should-not-run" not in result.output
        assert result.metadata["exit_code"] != 0

    @pytest.mark.asyncio
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
    async def test_windows_powershell_error_output_is_utf8(
        self,
        tool: BashTool,
        ctx: Context,
    ):
        result = await tool.call(
            tool.input_schema(command="Write-Error '测试错误'"),
            ctx,
        )

        assert "测试错误" in result.output


# -- 权限检查 ----------------------------------------------------------------


class TestPermission:
    def test_restricted_mode_denied(self, tool: BashTool, ctx: Context):
        ctx_restricted = Context(
            vault_path=ctx.vault_path,
            permission_level="restricted",
        )
        params = tool.input_schema(command="echo test")
        assert tool.check_permission(params, ctx_restricted) is False

    def test_normal_mode_allowed(self, tool: BashTool, ctx: Context):
        params = tool.input_schema(command="echo test")
        assert tool.check_permission(params, ctx) is True


# -- 环境变量清理 ------------------------------------------------------------


class TestEnvCleaning:
    def test_sensitive_vars_removed(self, tool: BashTool):
        with patch.dict("os.environ", {"MY_API_KEY": "secret123", "HOME": "/home/user"}):
            env = tool._clean_env()
            assert "MY_API_KEY" not in env
            assert "HOME" in env


class TestBackgroundExecution:
    @pytest.mark.asyncio
    async def test_background_task_keeps_output_after_idle_gap(
        self,
        tool: BashTool,
        ctx: Context,
        monkeypatch: pytest.MonkeyPatch,
    ):
        notifications: list[tuple[str, str]] = []

        async def fake_push_notification(conversation_id: str, message: str) -> None:
            notifications.append((conversation_id, message))

        monkeypatch.setattr(
            websocket_api,
            "push_notification",
            fake_push_notification,
        )

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            (
                "import time; "
                "print('first', flush=True); "
                "time.sleep(0.5); "
                "print('second', flush=True)"
            ),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ctx.vault_path),
            env=tool._clean_env(),
        )

        await bash_module._run_background_task(
            process,
            "python delayed-output test",
            "conversation-1",
        )

        assert notifications
        assert notifications[0][0] == "conversation-1"
        assert "first" in notifications[0][1]
        assert "second" in notifications[0][1]
