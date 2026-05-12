"""Helpers for loading MCP server definitions from local config files."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Mapping

from dotenv import dotenv_values
from pydantic import BaseModel, Field, ValidationError, model_validator

from config import ENV_FILE, MCP_CONFIG_FILE

logger = logging.getLogger(__name__)

_ENV_REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MCPConfigError(ValueError):
    """Raised when MCP configuration content is invalid."""


class MissingEnvironmentVariableError(MCPConfigError):
    """Raised when a ${VAR} reference cannot be resolved."""

    def __init__(self, variable_name: str) -> None:
        super().__init__(f"Missing environment variable: {variable_name}")
        self.variable_name = variable_name


class MCPServerDefinition(BaseModel):
    transport: str = "stdio"
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None
    url: str = ""

    @model_validator(mode="after")
    def validate_definition(self) -> "MCPServerDefinition":
        if self.transport not in {"stdio", "sse"}:
            raise ValueError(
                f"Unsupported transport {self.transport!r}; expected 'stdio' or 'sse'",
            )
        if self.transport == "stdio" and not self.command.strip():
            raise ValueError("stdio MCP servers require a non-empty 'command'")
        if self.transport == "sse" and not self.url.strip():
            raise ValueError("sse MCP servers require a non-empty 'url'")
        return self


def load_env_lookup(env_file: Path = ENV_FILE) -> dict[str, str]:
    """Load raw variables from the .env file for MCP interpolation."""
    if not env_file.is_file():
        return {}
    return {
        key: value
        for key, value in dotenv_values(env_file).items()
        if value is not None
    }


def _resolve_string(value: str, env_lookup: Mapping[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        variable_name = match.group(1)
        resolved = os.environ.get(variable_name)
        if resolved is None:
            resolved = env_lookup.get(variable_name)
        if resolved is None:
            raise MissingEnvironmentVariableError(variable_name)
        return resolved

    return _ENV_REF_PATTERN.sub(replace, value)


def _resolve_value(value: Any, env_lookup: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, env_lookup)
    if isinstance(value, list):
        return [_resolve_value(item, env_lookup) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _resolve_value(item, env_lookup)
            for key, item in value.items()
        }
    return value


def _validate_server_definition(
    *,
    name: str,
    raw_definition: Any,
    env_lookup: Mapping[str, str],
) -> dict[str, Any]:
    if not isinstance(raw_definition, dict):
        raise MCPConfigError(f"MCP server {name!r} must be an object")

    resolved_definition = _resolve_value(raw_definition, env_lookup)
    try:
        definition = MCPServerDefinition.model_validate(resolved_definition)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise MCPConfigError(f"Invalid MCP server {name!r}: {exc}") from exc

    config = definition.model_dump()
    config["name"] = name
    return config


def parse_mcp_config_payload(
    payload: Any,
    *,
    env_lookup: Mapping[str, str] | None = None,
    skip_invalid: bool = False,
) -> list[dict[str, Any]]:
    """Parse the preferred MCP config payload shape."""
    if not isinstance(payload, dict):
        raise MCPConfigError("MCP config must be a JSON object")

    raw_servers = payload.get("mcpServers", {})
    if not isinstance(raw_servers, dict):
        raise MCPConfigError("'mcpServers' must be an object")

    resolved_configs: list[dict[str, Any]] = []
    lookup = env_lookup or {}

    for name, raw_definition in raw_servers.items():
        try:
            resolved_configs.append(
                _validate_server_definition(
                    name=str(name),
                    raw_definition=raw_definition,
                    env_lookup=lookup,
                ),
            )
        except MCPConfigError:
            if not skip_invalid:
                raise
            logger.exception("Skipping invalid MCP server %s from config file", name)

    return resolved_configs


def load_mcp_server_configs(
    *,
    config_path: Path = MCP_CONFIG_FILE,
    env_file: Path = ENV_FILE,
    skip_invalid: bool = False,
) -> list[dict[str, Any]]:
    """Load MCP server configs from the local JSON file."""
    env_lookup = load_env_lookup(env_file)

    if not config_path.is_file():
        logger.info("MCP config file not found at %s; starting without MCP servers", config_path)
        return []

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPConfigError(
            f"Invalid JSON in MCP config file: {config_path}",
        ) from exc

    return parse_mcp_config_payload(
        payload,
        env_lookup=env_lookup,
        skip_invalid=skip_invalid,
    )
