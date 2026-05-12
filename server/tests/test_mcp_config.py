"""MCP config loading tests."""

from __future__ import annotations

import json

import pytest

from mcp_config import MCPConfigError, load_mcp_server_configs, parse_mcp_config_payload


def test_parse_mcp_config_payload_supports_stdio_and_sse() -> None:
    payload = {
        "mcpServers": {
            "minimax": {
                "transport": "stdio",
                "command": "uvx",
                "args": ["minimax-coding-plan-mcp", "-y"],
            },
            "mempalace": {
                "transport": "sse",
                "url": "http://127.0.0.1:8001/sse",
            },
        },
    }

    result = parse_mcp_config_payload(payload)

    assert result == [
        {
            "name": "minimax",
            "transport": "stdio",
            "command": "uvx",
            "args": ["minimax-coding-plan-mcp", "-y"],
            "env": None,
            "url": "",
        },
        {
            "name": "mempalace",
            "transport": "sse",
            "command": "",
            "args": [],
            "env": None,
            "url": "http://127.0.0.1:8001/sse",
        },
    ]


@pytest.mark.parametrize(
    ("payload", "expected_message"),
    [
        (
            {
                "mcpServers": {
                    "broken": {
                        "transport": "stdio",
                        "args": ["missing-command"],
                    },
                },
            },
            "command",
        ),
        (
            {
                "mcpServers": {
                    "broken": {
                        "transport": "sse",
                    },
                },
            },
            "url",
        ),
        (
            {
                "mcpServers": {
                    "broken": {
                        "transport": "streamable_http",
                        "url": "https://example.com/mcp",
                    },
                },
            },
            "Unsupported transport",
        ),
    ],
)
def test_parse_mcp_config_payload_rejects_invalid_entries(payload, expected_message: str) -> None:
    with pytest.raises(MCPConfigError, match=expected_message):
        parse_mcp_config_payload(payload)


def test_load_mcp_server_configs_resolves_env_refs_with_os_env_first(
    tmp_path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("MINIMAX_API_KEY=from-dotenv\n", encoding="utf-8")

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "MiniMax": {
                        "transport": "stdio",
                        "command": "uvx",
                        "args": ["minimax-coding-plan-mcp", "-y"],
                        "env": {
                            "MINIMAX_API_KEY": "${MINIMAX_API_KEY}",
                            "MINIMAX_API_HOST": "https://api.minimaxi.com",
                        },
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("MINIMAX_API_KEY", "from-os")

    result = load_mcp_server_configs(config_path=config_path, env_file=env_path)

    assert result[0]["args"] == ["minimax-coding-plan-mcp", "-y"]
    assert result[0]["env"] == {
        "MINIMAX_API_KEY": "from-os",
        "MINIMAX_API_HOST": "https://api.minimaxi.com",
    }


def test_load_mcp_server_configs_skips_missing_env_refs_when_requested(tmp_path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "broken": {
                        "transport": "stdio",
                        "command": "uvx",
                        "env": {"MINIMAX_API_KEY": "${MINIMAX_API_KEY}"},
                    },
                    "healthy": {
                        "transport": "sse",
                        "url": "http://127.0.0.1:8001/sse",
                    },
                },
            },
        ),
        encoding="utf-8",
    )

    result = load_mcp_server_configs(
        config_path=config_path,
        env_file=tmp_path / ".env",
        skip_invalid=True,
    )

    assert [item["name"] for item in result] == ["healthy"]


def test_load_mcp_server_configs_returns_empty_list_when_file_is_missing(tmp_path) -> None:
    result = load_mcp_server_configs(config_path=tmp_path / "missing.json")

    assert result == []


def test_load_mcp_server_configs_rejects_invalid_json(tmp_path) -> None:
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text("{not-json}", encoding="utf-8")

    with pytest.raises(MCPConfigError, match="Invalid JSON"):
        load_mcp_server_configs(config_path=config_path)
