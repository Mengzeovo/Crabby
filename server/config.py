"""Application configuration via environment variables."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

SERVER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SERVER_DIR.parent

# Resolve vault path: set by the Obsidian plugin at startup, or fall back to repo root
_vaulthome = Path(os.environ.get("VAULT_PATH") or PROJECT_ROOT).resolve()

# All runtime data lives under the vault, not the repo.
# .env lives at vault/.crabby/config/.env in production, repo/.env in dev.
CRABBY_SUBDIR = ".crabby"
CRABBY_CONFIG_DIR = _vaulthome / CRABBY_SUBDIR / "config"
CRABBY_DATA_DIR = _vaulthome / CRABBY_SUBDIR / "data"
CRABBY_LOGS_DIR = _vaulthome / CRABBY_SUBDIR / "logs"

ENV_FILE = CRABBY_CONFIG_DIR / ".env"
DATA_DIR = Path(os.environ.get("DATA_DIR") or CRABBY_DATA_DIR).resolve()
LOG_DIR = Path(os.environ.get("LOG_DIR") or CRABBY_LOGS_DIR).resolve()
MCP_CONFIG_FILE = Path(
    os.environ.get("MCP_CONFIG_FILE")
    or (CRABBY_CONFIG_DIR / "mcp_servers.json"),
).resolve()
DEFAULT_CORS_ALLOWED_ORIGINS = [
    "app://obsidian.md",
    "http://127.0.0.1",
    "http://localhost",
]


def _parse_json_list(raw: str | list[str] | None, *, fallback: list[str]) -> list[str]:
    if raw is None:
        return list(fallback)
    if isinstance(raw, list):
        return list(raw)

    text = raw.strip()
    if not text:
        return list(fallback)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [item.strip() for item in text.split(",") if item.strip()]

    if not isinstance(parsed, list):
        return list(fallback)

    return [str(item) for item in parsed if str(item).strip()]


class Settings(BaseSettings):
    # Vault
    vault_path: Path = _vaulthome

    # LLM
    llm_provider: str = "anthropic"  # "anthropic" | "openai" | "deepseek" | "custom_openai"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_base_url: str = ""
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    bailian_coding_plan_api_key: str = ""
    moonshot_api_key: str = ""
    kimi_api_key: str = ""
    kimi_base_url: str = ""
    minimax_api_key: str = ""
    zai_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"
    llm_supports_vision: bool = False
    llm_thinking_mode: str = ""
    llm_thinking_budget_tokens: int = 1024
    llm_reasoning_effort: str = ""
    llm_reasoning_split: bool = False

    # Tooling
    bash_enabled: bool = True
    bash_timeout: int = 30
    bash_max_timeout: int = 120

    # Hooks
    auto_save_interval: int = 15

    # Skills
    skills_enabled: bool = True
    skills_dir: str = ""

    # Prompts
    prompts_dir: str = ""

    # Personas
    personas_enabled: bool = True
    personas_dir: str = ""
    persona_router_threshold: float = 0.75

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    cors_allowed_origins: str = json.dumps(DEFAULT_CORS_ALLOWED_ORIGINS)

    # Local admin plane
    crabby_admin_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "CRABBY_ADMIN_ENABLED",
            "LIFE_ASSISTANT_ADMIN_ENABLED",
        ),
    )
    crabby_admin_token: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CRABBY_ADMIN_TOKEN",
            "LIFE_ASSISTANT_ADMIN_TOKEN",
        ),
    )
    crabby_host_heartbeat_file: str = Field(
        default="",
        validation_alias=AliasChoices(
            "CRABBY_HOST_HEARTBEAT_FILE",
            "LIFE_ASSISTANT_HOST_HEARTBEAT_FILE",
        ),
    )
    crabby_host_heartbeat_timeout_seconds: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "CRABBY_HOST_HEARTBEAT_TIMEOUT_SECONDS",
            "LIFE_ASSISTANT_HOST_HEARTBEAT_TIMEOUT_SECONDS",
        ),
    )
    crabby_host_pid: int = Field(
        default=0,
        validation_alias=AliasChoices(
            "CRABBY_HOST_PID",
            "LIFE_ASSISTANT_HOST_PID",
        ),
    )
    crabby_backend_reloader_parent: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "CRABBY_BACKEND_RELOADER_PARENT",
            "LIFE_ASSISTANT_BACKEND_RELOADER_PARENT",
        ),
    )

    # MemPalace
    mempalace_palace_path: str = Field(
        default="",
        validation_alias=AliasChoices(
            "MEMPALACE_PALACE_PATH",
            "LIFE_ASSISTANT_MEMPALACE_PALACE_PATH",
        ),
    )

    # Vault tools
    vault_tools_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "VAULT_TOOLS_ENABLED",
            "CRABBY_VAULT_TOOLS_ENABLED",
        ),
    )

    # MemPalace Ollama embedding (passed to MemPalace subprocess via mcp_servers.json)
    ollama_embedding_model: str = Field(
        default="",
        validation_alias="OLLAMA_EMBEDDING_MODEL",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """Return the allowed business API CORS origins."""
        return _parse_json_list(
            self.cors_allowed_origins,
            fallback=DEFAULT_CORS_ALLOWED_ORIGINS,
        )

    model_config = {
        "env_file": str(ENV_FILE),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def reload_settings() -> None:
    """Hot-reload settings from the mounted .env file."""
    new_settings = Settings()
    for field in sorted(Settings.model_fields.keys()):
        setattr(settings, field, getattr(new_settings, field))
