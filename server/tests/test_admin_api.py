"""Admin reload API tests."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import config
import llm.client as llm_client
import mcp_runtime
from api import admin as admin_api
from api.admin import router as admin_router
from mcp_config import load_mcp_server_configs as real_load_mcp_server_configs
from tools.base import Context, Tool, ToolResult
from tools.registry import ToolRegistry


def _build_admin_app() -> FastAPI:
    app = FastAPI()
    app.include_router(admin_router)
    return app


async def _noop_reload_mcp_servers(_app: FastAPI) -> dict[str, object]:
    return {}


class _EmptyParams(BaseModel):
    pass


class _NamedTool(Tool):
    description = "test tool"
    input_schema = _EmptyParams

    def __init__(self, name: str) -> None:
        self.name = name

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        return ToolResult(output=self.name)


class _FakeSession:
    def __init__(self, server_name: str) -> None:
        self.server_name = server_name


class _FakeMCPManager:
    instances: list["_FakeMCPManager"] = []
    failing_servers: set[str] = set()

    def __init__(self) -> None:
        self.connected_servers: list[str] = []
        self.configs: list[object] = []
        self.disconnected = False
        _FakeMCPManager.instances.append(self)

    async def connect(self, config_obj) -> _FakeSession:
        if config_obj.name in self.failing_servers:
            raise RuntimeError(f"connect failed for {config_obj.name}")
        self.configs.append(config_obj)
        self.connected_servers.append(config_obj.name)
        return _FakeSession(config_obj.name)

    async def disconnect_all(self) -> None:
        self.disconnected = True
        self.connected_servers.clear()


def _install_admin_runtime(monkeypatch, config_path: Path) -> None:
    monkeypatch.setattr(admin_api, "reload_settings", lambda: None)
    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")
    monkeypatch.setattr(mcp_runtime, "MCPClientManager", _FakeMCPManager)
    monkeypatch.setattr(
        mcp_runtime,
        "load_mcp_server_configs",
        lambda: real_load_mcp_server_configs(config_path=config_path),
    )


def test_admin_reload_returns_404_when_disabled(monkeypatch):
    monkeypatch.setattr(admin_api, "reload_mcp_servers", _noop_reload_mcp_servers)
    monkeypatch.setattr(config.settings, "crabby_admin_enabled", False)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 404


def test_admin_reload_returns_403_for_wrong_token(monkeypatch):
    monkeypatch.setattr(admin_api, "reload_mcp_servers", _noop_reload_mcp_servers)
    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "wrong"},
        )

    assert response.status_code == 403


def test_admin_shutdown_requires_token_and_requests_process_shutdown(monkeypatch):
    called: list[bool] = []
    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")
    monkeypatch.setattr(admin_api, "request_process_shutdown", lambda: called.append(True))

    with TestClient(_build_admin_app()) as client:
        forbidden = client.post(
            "/admin/shutdown",
            headers={"X-Crabby-Admin-Token": "wrong"},
        )
        response = client.post(
            "/admin/shutdown",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert response.json() == {"status": "shutting_down"}
    assert called == [True]


def test_admin_profile_test_requires_token(monkeypatch):
    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")

    with TestClient(_build_admin_app()) as client:
        missing = client.post("/admin/profile/test")
        forbidden = client.post(
            "/admin/profile/test",
            headers={"X-Crabby-Admin-Token": "wrong"},
        )

    assert missing.status_code == 403
    assert forbidden.status_code == 403


def test_admin_profiles_roundtrip_uses_env_as_source(monkeypatch, tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "EXTRA_SETTING=keep-me",
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    with TestClient(_build_admin_app()) as client:
        empty = client.get(
            "/admin/profiles",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        saved = client.put(
            "/admin/profiles/deepseek",
            headers={"X-Crabby-Admin-Token": "secret"},
            json={
                "activate": True,
                "profile": {
                    "id": "deepseek",
                    "name": "DeepSeek",
                    "provider": "openai",
                    "model": "deepseek-reasoner",
                    "baseUrl": "https://api.deepseek.com",
                    "apiKey": "provider-secret",
                    "supportsVision": False,
                    "thinkingMode": "enabled",
                    "thinkingEffort": "high",
                    "thinkingBudgetTokens": "1024",
                    "reasoningSplit": False,
                },
            },
        )

    assert empty.status_code == 200
    assert empty.json()["profiles"] == []
    assert saved.status_code == 200
    saved_data = saved.json()
    assert saved_data["activeProfileId"] == "deepseek"
    assert saved_data["profiles"][0]["provider"] == "deepseek"
    assert config.settings.llm_provider == "deepseek"
    assert config.settings.llm_model == "deepseek-reasoner"
    env_content = env_path.read_text(encoding="utf-8")
    assert "EXTRA_SETTING=keep-me" in env_content
    assert "PROFILE_deepseek_MODEL=deepseek-reasoner" in env_content
    assert "ACTIVE_PROFILE_ID=deepseek" in env_content
    assert "DEEPSEEK_API_KEY=provider-secret" in env_content

    with TestClient(_build_admin_app()) as client:
        deleted = client.delete(
            "/admin/profiles/deepseek",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert deleted.status_code == 200
    assert deleted.json()["profiles"] == []
    deleted_content = env_path.read_text(encoding="utf-8")
    assert "PROFILE_deepseek_" not in deleted_content
    assert "ACTIVE_PROFILE_ID=deepseek" not in deleted_content


def test_admin_profile_rejects_env_unsafe_id(monkeypatch, tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    with TestClient(_build_admin_app()) as client:
        saved = client.put(
            "/admin/profiles/profile-with-hyphen",
            headers={"X-Crabby-Admin-Token": "secret"},
            json={
                "activate": True,
                "profile": {
                    "id": "profile-with-hyphen",
                    "name": "Unsafe",
                    "provider": "openai",
                    "model": "gpt-4.1",
                    "baseUrl": "https://api.openai.com/v1",
                    "apiKey": "provider-secret",
                    "supportsVision": False,
                    "thinkingMode": "",
                    "thinkingEffort": "",
                    "thinkingBudgetTokens": "1024",
                    "reasoningSplit": False,
                },
            },
        )

    assert saved.status_code == 400
    assert "letters, numbers, or '_'" in saved.json()["detail"]
    assert "PROFILE_profile-with-hyphen_MODEL" not in env_path.read_text(
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("provider", "model", "delta", "expected_field"),
    [
        (
            "deepseek",
            "deepseek-reasoner",
            {"reasoning_content": "thinking"},
            "reasoning_content",
        ),
        (
            "kimi",
            "kimi-for-coding",
            {"reasoning_content": "thinking"},
            "reasoning_content",
        ),
        (
            "minimax",
            "MiniMax-M2.7",
            {"reasoning_details": [{"text": "thinking"}]},
            "reasoning_details",
        ),
    ],
)
def test_admin_profile_test_live_probes_reasoning_provider(
    monkeypatch,
    provider: str,
    model: str,
    delta: dict[str, object],
    expected_field: str,
):
    class FakeStreamResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def raise_for_status(self):
            return None

        async def aiter_lines(self):
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": delta,
                            "finish_reason": None,
                        }
                    ]
                }
            )
            yield "data: " + json.dumps(
                {
                    "choices": [
                        {
                            "delta": {"content": "OK"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )
            yield "data: [DONE]"

    class FakeAsyncClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, *_args, **_kwargs):
            return FakeStreamResponse()

    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")
    monkeypatch.setattr(config.settings, "llm_provider", provider)
    monkeypatch.setattr(config.settings, "llm_model", model)
    monkeypatch.setattr(config.settings, "llm_api_key", "provider-secret")
    monkeypatch.setattr(config.settings, "llm_base_url", "")
    monkeypatch.setattr(config.settings, "llm_reasoning_split", provider == "minimax")
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FakeAsyncClient)

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/profile/test",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == provider
    assert data["live_probe"] is True
    assert data["reasoning_detected"] is True
    assert data["reasoning_field"] == expected_field


def test_admin_profile_test_validates_non_live_provider_without_network(monkeypatch):
    class FailingAsyncClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("OpenAI validation should not call the network")

    monkeypatch.setattr(config.settings, "crabby_admin_enabled", True)
    monkeypatch.setattr(config.settings, "crabby_admin_token", "secret")
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", "gpt-5.4-mini")
    monkeypatch.setattr(config.settings, "llm_api_key", "provider-secret")
    monkeypatch.setattr(config.settings, "llm_base_url", "")
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", FailingAsyncClient)

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/profile/test",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["provider"] == "openai"
    assert data["live_probe"] is False
    assert data["reasoning_detected"] is None


def test_admin_reload_settings_refreshes_settings_from_env_file(monkeypatch, tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_MODEL=before-reload",
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    env_path.write_text(
        "\n".join(
            [
                "LLM_MODEL=after-reload",
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "settings_reloaded"}
    assert config.settings.llm_model == "after-reload"


def test_admin_reload_settings_syncs_bash_tool_and_auto_save_interval(
    monkeypatch,
    tmp_path: Path,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
                "BASH_ENABLED=true",
                "AUTO_SAVE_INTERVAL=15",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    app = _build_admin_app()
    registry = ToolRegistry()
    app.state.tool_registry = registry

    with TestClient(app) as client:
        enabled = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        assert enabled.status_code == 200
        assert registry.get("bash") is not None
        assert config.settings.auto_save_interval == 15

        env_path.write_text(
            "\n".join(
                [
                    "CRABBY_ADMIN_ENABLED=true",
                    "CRABBY_ADMIN_TOKEN=secret",
                    "BASH_ENABLED=false",
                    "AUTO_SAVE_INTERVAL=0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        disabled = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        assert disabled.status_code == 200
        assert registry.get("bash") is None
        assert config.settings.auto_save_interval == 0

        env_path.write_text(
            "\n".join(
                [
                    "CRABBY_ADMIN_ENABLED=true",
                    "CRABBY_ADMIN_TOKEN=secret",
                    "BASH_ENABLED=true",
                    "AUTO_SAVE_INTERVAL=23",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        reenabled = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert reenabled.status_code == 200
    assert registry.get("bash") is not None
    assert config.settings.auto_save_interval == 23


def test_admin_reload_settings_does_not_reload_mcp(monkeypatch, tmp_path: Path):
    def fail_if_mcp_reloads(_app: FastAPI):
        raise AssertionError("MCP reload should not run for /admin/reload-settings")

    monkeypatch.setattr(admin_api, "reload_mcp_servers", fail_if_mcp_reloads)
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LLM_MODEL=after-reload",
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    with TestClient(_build_admin_app()) as client:
        response = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "settings_reloaded"}


def test_admin_reload_settings_refreshes_persona_registry(monkeypatch, tmp_path: Path):
    from api.rest import router as rest_router

    first_dir = tmp_path / "personas-first"
    second_dir = tmp_path / "personas-second"
    (first_dir / "alpha").mkdir(parents=True)
    (second_dir / "beta").mkdir(parents=True)
    (first_dir / "alpha" / "PERSONA.md").write_text(
        "---\n"
        "id: alpha\n"
        "title: Alpha\n"
        "description: First persona\n"
        "---\n\n"
        "Alpha body\n",
        encoding="utf-8",
    )
    (second_dir / "beta" / "PERSONA.md").write_text(
        "---\n"
        "id: beta\n"
        "title: Beta\n"
        "description: Second persona\n"
        "---\n\n"
        "Beta body\n",
        encoding="utf-8",
    )

    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "CRABBY_ADMIN_ENABLED=true",
                "CRABBY_ADMIN_TOKEN=secret",
                f"PERSONAS_DIR={first_dir}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(config.Settings.model_config, "env_file", str(env_path))
    config.reload_settings()

    app = _build_admin_app()
    app.include_router(rest_router)

    with TestClient(app) as client:
        first_reload = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        before = client.get("/personas")
        env_path.write_text(
            "\n".join(
                [
                    "CRABBY_ADMIN_ENABLED=true",
                    "CRABBY_ADMIN_TOKEN=secret",
                    f"PERSONAS_DIR={second_dir}",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        reload_response = client.post(
            "/admin/reload-settings",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        after = client.get("/personas")

    assert first_reload.status_code == 200
    assert before.status_code == 200
    assert before.json() == [
        {"id": "alpha", "title": "Alpha", "description": "First persona"}
    ]
    assert reload_response.status_code == 200
    assert after.status_code == 200
    assert after.json() == [
        {"id": "beta", "title": "Beta", "description": "Second persona"}
    ]


def test_admin_reload_refreshes_mcp_runtime_from_config_file(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        '{"mcpServers":{"alpha":{"transport":"stdio","command":"uvx","args":["alpha-mcp"]}}}',
        encoding="utf-8",
    )

    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_tool"), source="builtin")

    app = _build_admin_app()
    app.state.tool_registry = registry
    app.state.mcp_reload_lock = asyncio.Lock()

    _install_admin_runtime(monkeypatch, config_path)

    async def fake_register_mcp_tools(session, registry_obj, server_name):
        registry_obj.register(
            _NamedTool(f"{server_name}_tool"),
            source="mcp",
            metadata={"server_name": server_name, "tool_name": f"{server_name}_tool"},
        )
        return 1

    monkeypatch.setattr(mcp_runtime, "register_mcp_tools", fake_register_mcp_tools)

    _FakeMCPManager.instances.clear()
    _FakeMCPManager.failing_servers.clear()
    asyncio.run(mcp_runtime.reload_mcp_servers(app))

    assert registry.get("builtin_tool") is not None
    assert registry.get("alpha_tool") is not None

    config_path.write_text(
        '{"mcpServers":{"beta":{"transport":"stdio","command":"uvx","args":["beta-mcp"]}}}',
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        status_response = client.get(
            "/admin/mcp/status",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 200
    assert response.json() == {"status": "reloaded"}
    assert status_response.status_code == 200
    assert status_response.json()["connected_servers"] == ["beta"]
    assert status_response.json()["tools_by_server"] == {"beta": ["beta_tool"]}
    assert status_response.json()["vault_tools_enabled"] is False
    assert status_response.json()["vault_tools_tools"] == []
    assert registry.get("builtin_tool") is not None
    assert registry.get("alpha_tool") is None
    assert registry.get("beta_tool") is not None
    assert _FakeMCPManager.instances[-2].disconnected is True
    assert _FakeMCPManager.instances[-1].connected_servers == ["beta"]


def test_mcp_reload_starts_vault_tools_with_backend_flag_when_frozen(
    monkeypatch,
    tmp_path: Path,
):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text('{"mcpServers":{}}', encoding="utf-8")

    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_tool"), source="builtin")

    app = _build_admin_app()
    app.state.tool_registry = registry
    app.state.mcp_reload_lock = asyncio.Lock()

    _install_admin_runtime(monkeypatch, config_path)
    vault_path = tmp_path / "vault"
    data_dir = tmp_path / "data"
    backend_exe = tmp_path / "crabby-backend.exe"
    monkeypatch.setattr(config.settings, "vault_tools_enabled", True)
    monkeypatch.setattr(config.settings, "vault_path", vault_path)
    monkeypatch.setattr(mcp_runtime, "DATA_DIR", data_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(backend_exe))

    async def fake_register_mcp_tools(session, registry_obj, server_name):
        registry_obj.register(
            _NamedTool("vault_hello"),
            source="mcp",
            metadata={"server_name": server_name, "tool_name": "vault_hello"},
        )
        return 1

    monkeypatch.setattr(mcp_runtime, "register_mcp_tools", fake_register_mcp_tools)

    _FakeMCPManager.instances.clear()
    _FakeMCPManager.failing_servers.clear()
    status = asyncio.run(mcp_runtime.reload_mcp_servers(app))

    assert status["connected_servers"] == [mcp_runtime.VAULT_TOOLS_SERVER_NAME]
    assert status["vault_tools_enabled"] is True
    assert status["vault_tools_tools"] == ["vault_hello"]

    manager = _FakeMCPManager.instances[-1]
    assert len(manager.configs) == 1
    vault_tools_config = manager.configs[0]
    assert vault_tools_config.name == mcp_runtime.VAULT_TOOLS_SERVER_NAME
    assert vault_tools_config.command == str(backend_exe)
    assert vault_tools_config.args == [mcp_runtime.VAULT_TOOLS_RUNNER_ARG]
    assert vault_tools_config.env == {
        "VAULT_PATH": str(vault_path),
        "CRABBY_DATA_DIR": str(data_dir),
    }


def test_admin_reload_rolls_back_on_invalid_config(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        '{"mcpServers":{"alpha":{"transport":"stdio","command":"uvx","args":["alpha-mcp"]}}}',
        encoding="utf-8",
    )

    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_tool"), source="builtin")

    app = _build_admin_app()
    app.state.tool_registry = registry
    app.state.mcp_reload_lock = asyncio.Lock()

    _install_admin_runtime(monkeypatch, config_path)

    async def fake_register_mcp_tools(session, registry_obj, server_name):
        registry_obj.register(
            _NamedTool(f"{server_name}_tool"),
            source="mcp",
            metadata={"server_name": server_name, "tool_name": f"{server_name}_tool"},
        )
        return 1

    monkeypatch.setattr(mcp_runtime, "register_mcp_tools", fake_register_mcp_tools)

    _FakeMCPManager.instances.clear()
    _FakeMCPManager.failing_servers.clear()
    asyncio.run(mcp_runtime.reload_mcp_servers(app))
    previous_manager = app.state.mcp_manager

    config_path.write_text("{invalid-json}", encoding="utf-8")

    with TestClient(app) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        status_response = client.get(
            "/admin/mcp/status",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]
    assert app.state.mcp_manager is previous_manager
    assert registry.get("alpha_tool") is not None
    assert status_response.json()["connected_servers"] == ["alpha"]
    assert status_response.json()["last_reload_ok"] is False
    assert "Invalid JSON" in status_response.json()["last_reload_error"]


def test_admin_reload_rolls_back_on_duplicate_tool_name(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        '{"mcpServers":{"alpha":{"transport":"stdio","command":"uvx","args":["alpha-mcp"]}}}',
        encoding="utf-8",
    )

    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_tool"), source="builtin")

    app = _build_admin_app()
    app.state.tool_registry = registry
    app.state.mcp_reload_lock = asyncio.Lock()

    _install_admin_runtime(monkeypatch, config_path)

    async def fake_register_mcp_tools(session, registry_obj, server_name):
        tool_name = "builtin_tool" if server_name == "beta" else f"{server_name}_tool"
        registry_obj.register(
            _NamedTool(tool_name),
            source="mcp",
            metadata={"server_name": server_name, "tool_name": tool_name},
        )
        return 1

    monkeypatch.setattr(mcp_runtime, "register_mcp_tools", fake_register_mcp_tools)

    _FakeMCPManager.instances.clear()
    _FakeMCPManager.failing_servers.clear()
    asyncio.run(mcp_runtime.reload_mcp_servers(app))
    previous_manager = app.state.mcp_manager

    config_path.write_text(
        '{"mcpServers":{"beta":{"transport":"stdio","command":"uvx","args":["beta-mcp"]}}}',
        encoding="utf-8",
    )

    with TestClient(app) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 400
    assert "Duplicate tool name" in response.json()["detail"]
    assert app.state.mcp_manager is previous_manager
    assert registry.get("alpha_tool") is not None
    assert registry.get("builtin_tool") is not None
    assert registry.get("beta_tool") is None


def test_admin_reload_rolls_back_when_any_server_connection_fails(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        '{"mcpServers":{"alpha":{"transport":"stdio","command":"uvx","args":["alpha-mcp"]}}}',
        encoding="utf-8",
    )

    registry = ToolRegistry()
    registry.register(_NamedTool("builtin_tool"), source="builtin")

    app = _build_admin_app()
    app.state.tool_registry = registry
    app.state.mcp_reload_lock = asyncio.Lock()

    _install_admin_runtime(monkeypatch, config_path)

    async def fake_register_mcp_tools(session, registry_obj, server_name):
        registry_obj.register(
            _NamedTool(f"{server_name}_tool"),
            source="mcp",
            metadata={"server_name": server_name, "tool_name": f"{server_name}_tool"},
        )
        return 1

    monkeypatch.setattr(mcp_runtime, "register_mcp_tools", fake_register_mcp_tools)

    _FakeMCPManager.instances.clear()
    _FakeMCPManager.failing_servers.clear()
    asyncio.run(mcp_runtime.reload_mcp_servers(app))
    previous_manager = app.state.mcp_manager

    config_path.write_text(
        (
            '{"mcpServers":{'
            '"alpha":{"transport":"stdio","command":"uvx","args":["alpha-mcp"]},'
            '"beta":{"transport":"stdio","command":"uvx","args":["beta-mcp"]}'
            "}}"
        ),
        encoding="utf-8",
    )
    _FakeMCPManager.failing_servers = {"beta"}

    with TestClient(app) as client:
        response = client.post(
            "/admin/reload",
            headers={"X-Crabby-Admin-Token": "secret"},
        )
        status_response = client.get(
            "/admin/mcp/status",
            headers={"X-Crabby-Admin-Token": "secret"},
        )

    assert response.status_code == 400
    assert "connect failed for beta" in response.json()["detail"]
    assert app.state.mcp_manager is previous_manager
    assert registry.get("alpha_tool") is not None
    assert registry.get("beta_tool") is None
    assert status_response.json()["connected_servers"] == ["alpha"]
    assert status_response.json()["last_reload_ok"] is False
