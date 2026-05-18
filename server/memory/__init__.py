"""Short-term memory with session manifests and active-branch caching.

Sessions are persisted under ``sessions/{session_id}/manifest.json`` with
message bodies stored separately in ``conversations/{conversation_id}.json``.
The public ``Session`` API remains compatible with the previous flat message
history while the store can materialize the active branch through a process
local TTL/LRU cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from attachment_store import AttachmentStore
from personas import PersonaState
from user_turn import PreparedTurn, build_user_message_content

logger = logging.getLogger(__name__)

_session_store: "SessionStore | None" = None
_current_vault_path: Path | None = None

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
ROOT_CONVERSATION_ID = "root"
SESSION_SCHEMA_VERSION = 2
DEFAULT_BRANCH_CACHE_TTL_SECONDS = 30 * 60
DEFAULT_BRANCH_CACHE_MAX_BYTES = 64 * 1024 * 1024


def set_session_store(store: "SessionStore | None") -> None:
    global _session_store
    _session_store = store


def get_session_store() -> "SessionStore | None":
    return _session_store


def set_vault_path(path: Path | None) -> None:
    global _current_vault_path
    _current_vault_path = path


def get_vault_path() -> Path | None:
    return _current_vault_path


class InvalidSessionIdError(ValueError):
    """Raised when a caller provides an unsafe session identifier."""


class ConversationNotFoundError(ValueError):
    """Raised when a conversation does not exist in a session."""


class MessageNotFoundError(ValueError):
    """Raised when a message cannot be used as a fork point."""


class InvalidPathError(ValueError):
    """Raised when a resolved path falls outside the storage root."""


def validate_session_id(session_id: str) -> str:
    """Return *session_id* if it is safe to use as a session filename stem."""
    if not isinstance(session_id, str) or not session_id:
        raise InvalidSessionIdError("Session ID must be a non-empty string")
    if not _SESSION_ID_PATTERN.fullmatch(session_id):
        raise InvalidSessionIdError(
            "Session ID may only contain ASCII letters, digits, underscores, "
            "and hyphens, up to 128 characters"
        )
    return session_id


def validate_conversation_id(conversation_id: str) -> str:
    """Return *conversation_id* if it is safe to use as a JSON filename stem."""
    return validate_session_id(conversation_id)


def _is_tool_result_content(content: Any) -> bool:
    """Return True when a message content payload is purely tool results."""
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(block, dict) and block.get("type") == "tool_result"
        for block in content
    )


def _content_for_model(content: Any) -> Any:
    """Strip UI-only fields before sending persisted messages to providers."""
    if not isinstance(content, list):
        return content

    stripped: list[Any] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            stripped.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("tool_use_id"),
                    "content": block.get("content", ""),
                }
            )
            continue
        stripped.append(block)
    return stripped


def _clone_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return json.loads(json.dumps(messages, ensure_ascii=False))


def _serialized_message_bytes(messages: list[dict[str, Any]]) -> int:
    payload = json.dumps(
        messages,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return len(payload.encode("utf-8"))


def _new_message_id() -> str:
    return f"m_{uuid.uuid4().hex}"


@dataclass
class ConversationRecord:
    """A persisted conversation branch owned by one session."""

    id: str = ROOT_CONVERSATION_ID
    session_id: str = ""
    parent_id: str | None = None
    fork_message_id: str | None = None
    revision: int = 1
    created_at: float = field(default_factory=time.time)
    last_activity_at: float = field(default_factory=time.time)
    title: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    persisted_message_count: int = 0

    @property
    def file(self) -> str:
        return f"conversations/{self.id}.json"

    @property
    def message_count(self) -> int:
        if self.messages:
            return len(self.messages)
        return max(0, int(self.persisted_message_count or 0))

    def touch(self) -> None:
        self.last_activity_at = time.time()
        self.revision += 1

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "parent_id": self.parent_id,
            "fork_message_id": self.fork_message_id,
            "revision": self.revision,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "title": self.title,
            "message_count": self.message_count,
            "file": self.file,
        }

    def to_file_dict(self) -> dict[str, Any]:
        payload = self.to_manifest_dict()
        payload["messages"] = self.messages
        return payload

    @classmethod
    def from_file_dict(
        cls,
        data: dict[str, Any],
        *,
        session_id: str,
    ) -> ConversationRecord:
        conversation_id = validate_conversation_id(
            str(data.get("id") or ROOT_CONVERSATION_ID)
        )
        parent_id = data.get("parent_id")
        if parent_id is not None:
            parent_id = validate_conversation_id(str(parent_id))
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        return cls(
            id=conversation_id,
            session_id=session_id,
            parent_id=parent_id,
            fork_message_id=data.get("fork_message_id"),
            revision=max(1, int(data.get("revision") or 1)),
            created_at=float(data.get("created_at") or time.time()),
            last_activity_at=float(data.get("last_activity_at") or time.time()),
            title=str(data.get("title") or ""),
            messages=messages,
            persisted_message_count=len(messages),
        )

    @classmethod
    def from_manifest_dict(cls, data: dict[str, Any]) -> ConversationRecord:
        session_id = validate_session_id(str(data["session_id"]))
        conversation_id = validate_conversation_id(str(data["id"]))
        parent_id = data.get("parent_id")
        if parent_id is not None:
            parent_id = validate_conversation_id(str(parent_id))
        try:
            message_count = max(0, int(data.get("message_count") or 0))
        except (TypeError, ValueError):
            message_count = 0
        return cls(
            id=conversation_id,
            session_id=session_id,
            parent_id=parent_id,
            fork_message_id=data.get("fork_message_id"),
            revision=max(1, int(data.get("revision") or 1)),
            created_at=float(data.get("created_at") or time.time()),
            last_activity_at=float(data.get("last_activity_at") or time.time()),
            title=str(data.get("title") or ""),
            messages=[],
            persisted_message_count=message_count,
        )


@dataclass(frozen=True)
class BranchSnapshot:
    """A materialized active conversation branch."""

    session_id: str
    conversation_id: str
    lineage: list[str]
    branch_fingerprint: str
    messages: list[dict[str, Any]]
    size_bytes: int


@dataclass
class _BranchCacheEntry:
    lineage: list[str]
    branch_fingerprint: str
    messages: list[dict[str, Any]]
    size_bytes: int
    last_access_at: float


class BranchCache:
    """Process-local TTL/LRU cache for materialized active branches."""

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_BRANCH_CACHE_TTL_SECONDS,
        max_bytes: int = DEFAULT_BRANCH_CACHE_MAX_BYTES,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes
        self._now = now
        self._entries: OrderedDict[tuple[str, str], _BranchCacheEntry] = OrderedDict()
        self.total_bytes = 0

    def get(
        self,
        key: tuple[str, str],
        *,
        branch_fingerprint: str,
    ) -> BranchSnapshot | None:
        entry = self._entries.get(key)
        if entry is None:
            return None

        now = self._now()
        if now - entry.last_access_at > self.ttl_seconds:
            self.invalidate(key)
            return None
        if entry.branch_fingerprint != branch_fingerprint:
            self.invalidate(key)
            return None

        entry.last_access_at = now
        self._entries.move_to_end(key)
        session_id, conversation_id = key
        return BranchSnapshot(
            session_id=session_id,
            conversation_id=conversation_id,
            lineage=list(entry.lineage),
            branch_fingerprint=entry.branch_fingerprint,
            messages=_clone_messages(entry.messages),
            size_bytes=entry.size_bytes,
        )

    def set(
        self,
        key: tuple[str, str],
        *,
        lineage: list[str],
        branch_fingerprint: str,
        messages: list[dict[str, Any]],
    ) -> BranchSnapshot:
        size_bytes = _serialized_message_bytes(messages)
        self.invalidate(key)

        session_id, conversation_id = key
        snapshot = BranchSnapshot(
            session_id=session_id,
            conversation_id=conversation_id,
            lineage=list(lineage),
            branch_fingerprint=branch_fingerprint,
            messages=_clone_messages(messages),
            size_bytes=size_bytes,
        )

        entry = _BranchCacheEntry(
            lineage=list(lineage),
            branch_fingerprint=branch_fingerprint,
            messages=_clone_messages(messages),
            size_bytes=size_bytes,
            last_access_at=self._now(),
        )
        self._entries[key] = entry
        self.total_bytes += size_bytes
        self._evict_to_budget()
        return snapshot

    def invalidate(self, key: tuple[str, str]) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self.total_bytes -= entry.size_bytes

    def invalidate_session(self, session_id: str) -> None:
        keys = [key for key in self._entries if key[0] == session_id]
        for key in keys:
            self.invalidate(key)

    def clear(self) -> None:
        self._entries.clear()
        self.total_bytes = 0

    def __len__(self) -> int:
        return len(self._entries)

    def _evict_to_budget(self) -> None:
        while self.total_bytes > self.max_bytes and self._entries:
            _key, entry = self._entries.popitem(last=False)
            self.total_bytes -= entry.size_bytes


@dataclass
class Session:
    """One session container with one active materialized conversation branch."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = ""
    created_at: float = field(default_factory=time.time)
    messages: list[dict[str, Any]] = field(default_factory=list)
    pending_notifications: list[str] = field(default_factory=list)
    persona_state: PersonaState = field(default_factory=PersonaState)
    actual_usage_total: dict[str, int] = field(default_factory=dict)
    last_activity_at: float = 0.0
    root_conversation_id: str = ROOT_CONVERSATION_ID
    active_conversation_id: str = ROOT_CONVERSATION_ID
    conversation_revision: int = 1
    active_loop_id: str | None = None
    """ID of the currently active interactive loop for this session, if any."""
    vault_path: Path | None = None
    """Vault root path used to derive runtime data directories. Set at Session creation."""
    conversation_index: dict[str, ConversationRecord] = field(
        default_factory=dict,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.id = validate_session_id(self.id)
        self.root_conversation_id = validate_conversation_id(self.root_conversation_id)
        self.active_conversation_id = validate_conversation_id(
            self.active_conversation_id
        )
        if not self.last_activity_at:
            self.last_activity_at = self.created_at
        self.conversation_revision = max(1, int(self.conversation_revision or 1))
        if self.active_loop_id is not None:
            self.active_loop_id = validate_session_id(self.active_loop_id)
        # Auto-set vault_path from global state if not already set.
        if self.vault_path is None:
            self.vault_path = _current_vault_path
        if self.conversation_index:
            self.conversation_index = {
                validate_conversation_id(conversation_id): record
                for conversation_id, record in self.conversation_index.items()
            }
        else:
            active_record = ConversationRecord(
                id=self.active_conversation_id,
                session_id=self.id,
                revision=self.conversation_revision,
                created_at=self.created_at,
                last_activity_at=self.last_activity_at,
                title=self.title,
            )
            self.conversation_index = {self.active_conversation_id: active_record}

    # -- mutators ----------------------------------------------------------

    def add_user_message(self, content: str) -> None:
        self.messages.append(
            {"role": "user", "content": content, "message_id": _new_message_id()}
        )
        # Auto-title from first user message
        if not self.title:
            self.title = content[:30].strip()
        self._touch_messages_changed()

    def add_user_prepared_turn(self, turn: PreparedTurn) -> str:
        message_id = _new_message_id()
        message: dict[str, Any] = {
            "role": "user",
            "message_id": message_id,
            "text": turn.text,
            "model_text": turn.model_text,
            "attachments": turn.attachments,
        }
        if turn.command is not None:
            message["command"] = turn.command
        self.messages.append(message)
        if not self.title:
            self.title = self._derive_title_from_user_message(message)
        self._touch_messages_changed()
        return message_id

    def add_assistant_message(self, content: Any) -> str:
        message_id = _new_message_id()
        self.messages.append(
            {
                "role": "assistant",
                "content": content,
                "message_id": message_id,
            }
        )
        self._touch_messages_changed()
        return message_id

    def add_tool_result(self, content: Any) -> None:
        """Append a tool-result message (role=user with tool_result blocks)."""
        self.messages.append(
            {
                "role": "user",
                "content": content,
                "message_id": _new_message_id(),
            }
        )
        self._touch_messages_changed()

    def get_messages(
        self,
        attachment_store: AttachmentStore | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        source_messages = self.messages if messages is None else messages
        converted: list[dict[str, Any]] = []
        for message in source_messages:
            role = message.get("role", "")
            if role == "user" and "text" in message:
                converted.append(
                    {
                        "role": "user",
                        "content": build_user_message_content(
                            message,
                            attachment_store,
                        ),
                    }
                )
                continue

            converted.append(
                {
                    "role": role,
                    "content": _content_for_model(message.get("content", "")),
                }
            )
        return converted

    def get_ui_messages(
        self,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return the active branch payload as-is for frontend restoration."""
        source_messages = self.messages if messages is None else messages
        return _clone_messages(source_messages)

    def get_recent_user_turn_texts(self, limit: int = 3) -> list[str]:
        """Return recent user-authored turns, excluding tool results."""
        turns: list[str] = []
        for message in self.messages:
            if message.get("role") != "user":
                continue
            if _is_tool_result_content(message.get("content")):
                continue
            text = message.get("model_text", message.get("text", ""))
            normalized = str(text).strip()
            if normalized:
                turns.append(normalized)
        return turns[-limit:]

    @property
    def turn_count(self) -> int:
        """Number of real user turns, excluding tool-result payload messages."""
        return sum(
            1
            for message in self.messages
            if message["role"] == "user"
            and not _is_tool_result_content(message.get("content"))
        )

    def append_to_latest_user_message(self, extra_text: str) -> None:
        if not self.messages:
            return
        latest = self.messages[-1]
        if latest.get("role") != "user":
            return

        if "text" in latest:
            current_text = str(latest.get("text", ""))
            current_model_text = str(latest.get("model_text", current_text))
            latest["text"] = f"{current_text}{extra_text}"
            latest["model_text"] = f"{current_model_text}{extra_text}"
            self._touch_messages_changed()
            return

        content = latest.get("content")
        if isinstance(content, str):
            latest["content"] = content + extra_text
        elif isinstance(content, list):
            content.append({"type": "text", "text": extra_text})
        self._touch_messages_changed()

    def branch_lineage(self, conversation_id: str | None = None) -> list[str]:
        """Return the active branch lineage from root to active conversation."""
        lineage: list[str] = []
        seen: set[str] = set()
        target_conversation_id = conversation_id or self.active_conversation_id
        current_id: str | None = target_conversation_id

        while current_id:
            if current_id in seen:
                logger.warning(
                    "Cycle detected in conversation lineage for session %s at %s",
                    self.id,
                    current_id,
                )
                return [target_conversation_id]
            seen.add(current_id)
            record = self.conversation_index.get(current_id)
            if record is None:
                return [target_conversation_id]
            lineage.append(current_id)
            current_id = record.parent_id

        return list(reversed(lineage)) or [target_conversation_id]

    def branch_fingerprint(self, conversation_id: str | None = None) -> str:
        parts = []
        target_conversation_id = conversation_id or self.active_conversation_id
        for lineage_conversation_id in self.branch_lineage(target_conversation_id):
            record = self.conversation_index.get(lineage_conversation_id)
            revision = (
                self.conversation_revision
                if lineage_conversation_id == self.active_conversation_id
                else record.revision if record is not None else 1
            )
            parts.append(f"{lineage_conversation_id}:{revision}")
        raw = "|".join(parts)
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the legacy flat shape for compatibility with older callers."""
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "root_conversation_id": self.root_conversation_id,
            "active_conversation_id": self.active_conversation_id,
            "messages": self.messages,
            "pending_notifications": self.pending_notifications,
            "persona_state": self.persona_state.model_dump(),
            "actual_usage_total": self.actual_usage_total,
            "conversation_revision": self.conversation_revision,
            "active_loop_id": self.active_loop_id,
            "vault_path": str(self.vault_path) if self.vault_path else None,
        }

    def to_manifest_dict(self) -> dict[str, Any]:
        conversation_index = dict(self.conversation_index)
        active_conversation = self.to_conversation_record()
        conversation_index[active_conversation.id] = active_conversation
        return {
            "schema_version": SESSION_SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "last_activity_at": self.last_activity_at,
            "root_conversation_id": self.root_conversation_id,
            "active_conversation_id": self.active_conversation_id,
            "pending_notifications": self.pending_notifications,
            "persona_state": self.persona_state.model_dump(),
            "actual_usage_total": self.actual_usage_total,
            "active_loop_id": self.active_loop_id,
            "vault_path": str(self.vault_path) if self.vault_path else None,
            "conversations": {
                conversation.id: conversation.to_manifest_dict()
                for conversation in conversation_index.values()
            },
        }

    def to_conversation_record(self) -> ConversationRecord:
        existing = self.conversation_index.get(self.active_conversation_id)
        messages = self._active_conversation_messages_for_persist(existing)
        return ConversationRecord(
            id=self.active_conversation_id,
            session_id=self.id,
            parent_id=existing.parent_id if existing is not None else None,
            fork_message_id=(
                existing.fork_message_id if existing is not None else None
            ),
            revision=self.conversation_revision,
            created_at=existing.created_at if existing is not None else self.created_at,
            last_activity_at=self.last_activity_at,
            title=self._conversation_title_for_persist(existing),
            messages=messages,
            persisted_message_count=len(messages),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], vault_path: Path | None = None) -> Session:
        actual_usage_total = data.get("actual_usage_total", {})
        if not isinstance(actual_usage_total, dict):
            actual_usage_total = {}
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            messages = []
        created_at = float(data.get("created_at") or 0.0)
        # Prefer persisted vault_path, fall back to store-supplied value.
        vp = data.get("vault_path")
        resolved_vp: Path | None = None
        if vp:
            resolved_vp = Path(vp)
        elif vault_path is not None:
            resolved_vp = vault_path
        return cls(
            id=data["id"],
            title=data.get("title", ""),
            created_at=created_at,
            messages=messages,
            pending_notifications=data.get("pending_notifications", []),
            persona_state=PersonaState.model_validate(data.get("persona_state", {})),
            actual_usage_total=actual_usage_total,
            last_activity_at=float(data.get("last_activity_at") or created_at),
            root_conversation_id=str(
                data.get("root_conversation_id") or ROOT_CONVERSATION_ID
            ),
            active_conversation_id=str(
                data.get("active_conversation_id") or ROOT_CONVERSATION_ID
            ),
            conversation_revision=int(data.get("conversation_revision") or 1),
            active_loop_id=data.get("active_loop_id"),
            vault_path=resolved_vp,
        )

    @classmethod
    def from_manifest_and_conversation(
        cls,
        manifest: dict[str, Any],
        conversation: ConversationRecord,
        conversation_index: dict[str, ConversationRecord],
        vault_path: Path | None = None,
    ) -> Session:
        actual_usage_total = manifest.get("actual_usage_total", {})
        if not isinstance(actual_usage_total, dict):
            actual_usage_total = {}
        created_at = float(manifest.get("created_at") or conversation.created_at)
        active_conversation_id = str(
            manifest.get("active_conversation_id") or conversation.id
        )
        root_conversation_id = str(
            manifest.get("root_conversation_id") or conversation.id
        )
        # Prefer persisted vault_path, fall back to store-supplied value.
        vp = manifest.get("vault_path")
        resolved_vp: Path | None = None
        if vp:
            resolved_vp = Path(vp)
        elif vault_path is not None:
            resolved_vp = vault_path
        return cls(
            id=manifest["id"],
            title=manifest.get("title", conversation.title),
            created_at=created_at,
            messages=conversation.messages,
            pending_notifications=manifest.get("pending_notifications", []),
            persona_state=PersonaState.model_validate(
                manifest.get("persona_state", {})
            ),
            actual_usage_total=actual_usage_total,
            last_activity_at=float(
                manifest.get("last_activity_at") or conversation.last_activity_at
            ),
            root_conversation_id=root_conversation_id,
            active_conversation_id=active_conversation_id,
            conversation_revision=conversation.revision,
            conversation_index=conversation_index,
            active_loop_id=manifest.get("active_loop_id"),
            vault_path=resolved_vp,
        )

    def _derive_title_from_user_message(self, message: dict[str, Any]) -> str:
        text = str(message.get("text", "")).strip()
        if text:
            return text[:30]

        attachments = message.get("attachments")
        if isinstance(attachments, list) and attachments:
            first = attachments[0]
            if isinstance(first, dict):
                if first.get("type") == "image":
                    return str(first.get("filename", "Image"))[:30]
                return str(first.get("path", "Attachment"))[:30]
        return ""

    def _touch_messages_changed(self) -> None:
        self.last_activity_at = time.time()
        self.conversation_revision += 1
        record = self.conversation_index.get(self.active_conversation_id)
        if record is not None:
            record.revision = self.conversation_revision
            record.last_activity_at = self.last_activity_at
            record.persisted_message_count = len(
                self._active_conversation_messages_for_persist(record)
            )
            if record.parent_id is None:
                record.title = self.title

    def _active_conversation_messages_for_persist(
        self,
        existing: ConversationRecord | None,
    ) -> list[dict[str, Any]]:
        if existing is None or existing.parent_id is None or not existing.fork_message_id:
            return self.messages

        for index, message in enumerate(self.messages):
            if message.get("message_id") == existing.fork_message_id:
                return self.messages[index + 1 :]

        return self.messages

    def _conversation_title_for_persist(
        self,
        existing: ConversationRecord | None,
    ) -> str:
        if existing is None or existing.parent_id is None:
            return self.title
        return existing.title or "Forked conversation"


class SessionStore:
    """File-backed store for all sessions.

    The current layout is ``{session_id}/manifest.json`` plus conversation
    files. Legacy ``{session_id}.json`` files are read and rewritten into the
    new layout the first time they are loaded.
    """

    def __init__(
        self,
        max_sessions: int = 100,
        storage_dir: str | Path | None = None,
        branch_cache: BranchCache | None = None,
        vault_path: Path | None = None,
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._max_sessions = max_sessions
        self.branch_cache = branch_cache if branch_cache is not None else BranchCache()
        # Resolve vault_path at store creation time (before _load_all runs).
        # Falls back to the module-level global for sessions created before
        # set_vault_path() was called.
        self._vault_path = vault_path if vault_path is not None else _current_vault_path

        if storage_dir is None:
            self._storage_dir = (
                Path(__file__).resolve().parent.parent / "data" / "sessions"
            )
        else:
            self._storage_dir = Path(storage_dir)

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    # -- public API --------------------------------------------------------

    def create(self, session_id: str | None = None) -> Session:
        """Create a new session, evicting the oldest if at capacity."""
        safe_session_id = (
            validate_session_id(session_id) if session_id else uuid.uuid4().hex[:12]
        )
        if len(self._sessions) >= self._max_sessions:
            oldest_key = min(
                self._sessions,
                key=lambda key: self._sessions[key].last_activity_at,
            )
            self._delete_file(oldest_key)
            del self._sessions[oldest_key]
            self.branch_cache.invalidate_session(oldest_key)

        session = Session(id=safe_session_id)
        self._sessions[session.id] = session
        self._persist(session)
        return session

    def get(self, session_id: str) -> Session | None:
        try:
            safe_session_id = validate_session_id(session_id)
        except InvalidSessionIdError:
            return None
        return self._sessions.get(safe_session_id)

    def get_or_create(self, session_id: str | None) -> Session:
        """Get existing session or create a new one."""
        if not session_id:
            return self.create(None)

        safe_session_id = validate_session_id(session_id)
        if safe_session_id in self._sessions:
            return self._sessions[safe_session_id]
        return self.create(safe_session_id)

    def delete(self, session_id: str) -> bool:
        try:
            safe_session_id = validate_session_id(session_id)
        except InvalidSessionIdError:
            return False
        if safe_session_id in self._sessions:
            del self._sessions[safe_session_id]
            self._delete_file(safe_session_id)
            self.branch_cache.invalidate_session(safe_session_id)
            return True
        return False

    def persist(self, session: Session) -> None:
        """Persist a session to disk (public, called after mutations)."""
        self._persist(session)

    def list_sessions(self) -> list[dict[str, Any]]:
        # Return newest activity first
        sessions = sorted(
            self._sessions.values(),
            key=lambda s: s.last_activity_at,
            reverse=True,
        )
        return [
            {
                "id": s.id,
                "title": s.title,
                "turn_count": s.turn_count,
                "message_count": len(s.messages),
                "created_at": s.created_at,
                "last_activity_at": s.last_activity_at,
                "root_conversation_id": s.root_conversation_id,
                "active_conversation_id": s.active_conversation_id,
                "branch_fingerprint": s.branch_fingerprint(),
                "persona_state": s.persona_state.model_dump(),
            }
            for s in sessions
        ]

    def list_conversations(self, session_id: str) -> list[dict[str, Any]] | None:
        session = self.get(session_id)
        if session is None:
            return None
        records = sorted(
            session.conversation_index.values(),
            key=lambda record: (record.created_at, record.id),
        )
        return [
            {
                **record.to_manifest_dict(),
                "active": record.id == session.active_conversation_id,
                "branch_fingerprint": session.branch_fingerprint(record.id),
            }
            for record in records
        ]

    def conversation_exists(self, session_id: str, conversation_id: str) -> bool:
        session = self.get(session_id)
        if session is None:
            return False
        try:
            safe_conversation_id = validate_conversation_id(conversation_id)
        except InvalidSessionIdError:
            return False
        return safe_conversation_id in session.conversation_index

    def set_active_conversation(
        self,
        session_id: str,
        conversation_id: str,
        *,
        persist: bool = True,
    ) -> Session:
        session = self._require_session(session_id)
        safe_conversation_id = validate_conversation_id(conversation_id)
        record = session.conversation_index.get(safe_conversation_id)
        if record is None:
            raise ConversationNotFoundError(
                f"Conversation {safe_conversation_id} not found"
            )

        snapshot = self.get_branch_snapshot(session.id, safe_conversation_id)
        if snapshot is None:
            raise ConversationNotFoundError(
                f"Conversation {safe_conversation_id} not found"
            )

        session.active_conversation_id = safe_conversation_id
        session.conversation_revision = record.revision
        session.messages = snapshot.messages
        session.last_activity_at = max(
            session.last_activity_at,
            record.last_activity_at,
        )
        if persist:
            self._persist(session)
        return session

    def fork_conversation(
        self,
        session_id: str,
        parent_conversation_id: str,
        fork_message_id: str,
        *,
        title: str = "",
    ) -> tuple[Session, ConversationRecord]:
        session = self._require_session(session_id)
        safe_parent_id = validate_conversation_id(parent_conversation_id)
        if safe_parent_id not in session.conversation_index:
            raise ConversationNotFoundError(f"Conversation {safe_parent_id} not found")
        if not fork_message_id or not isinstance(fork_message_id, str):
            raise MessageNotFoundError("fork_message_id is required")

        parent_snapshot = self.get_branch_snapshot(session.id, safe_parent_id)
        if parent_snapshot is None:
            raise ConversationNotFoundError(f"Conversation {safe_parent_id} not found")

        fork_index = self._find_message_index(
            parent_snapshot.messages,
            fork_message_id,
        )
        if fork_index is None:
            raise MessageNotFoundError(
                f"Message {fork_message_id} was not found or cannot be used as a fork point"
            )

        conversation_id = self._new_conversation_id(session)
        now = time.time()
        record = ConversationRecord(
            id=conversation_id,
            session_id=session.id,
            parent_id=safe_parent_id,
            fork_message_id=fork_message_id,
            revision=1,
            created_at=now,
            last_activity_at=now,
            title=title.strip() or "Forked conversation",
            messages=[],
        )
        session.conversation_index[conversation_id] = record
        session.active_conversation_id = conversation_id
        session.conversation_revision = record.revision
        session.last_activity_at = now
        session.messages = parent_snapshot.messages[: fork_index + 1]
        self._persist(session)
        return session, record

    def get_active_branch_snapshot(self, session_id: str) -> BranchSnapshot | None:
        session = self.get(session_id)
        if session is None:
            return None
        return self.get_branch_snapshot(session_id, session.active_conversation_id)

    def get_branch_snapshot(
        self,
        session_id: str,
        conversation_id: str | None = None,
    ) -> BranchSnapshot | None:
        session = self.get(session_id)
        if session is None:
            return None

        target_conversation_id = conversation_id or session.active_conversation_id
        try:
            safe_conversation_id = validate_conversation_id(target_conversation_id)
        except InvalidSessionIdError:
            return None
        if safe_conversation_id not in session.conversation_index:
            return None

        lineage = session.branch_lineage(safe_conversation_id)
        fingerprint = session.branch_fingerprint(safe_conversation_id)
        key = (session.id, safe_conversation_id)
        cached = self.branch_cache.get(key, branch_fingerprint=fingerprint)
        if cached is not None:
            return cached

        messages = self._materialize_branch_from_disk(session, safe_conversation_id)
        return self.branch_cache.set(
            key,
            lineage=lineage,
            branch_fingerprint=fingerprint,
            messages=messages,
        )

    def get_ui_messages(
        self,
        session_id: str,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        session = self.get(session_id)
        if session is None:
            return None
        snapshot = self.get_branch_snapshot(session_id, conversation_id)
        if snapshot is None and conversation_id is not None:
            return None
        messages = snapshot.messages if snapshot is not None else session.messages
        return session.get_ui_messages(messages=messages)

    def get_model_messages(
        self,
        session_id: str,
        attachment_store: AttachmentStore | None = None,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]] | None:
        session = self.get(session_id)
        if session is None:
            return None
        snapshot = self.get_branch_snapshot(session_id, conversation_id)
        if snapshot is None and conversation_id is not None:
            return None
        messages = snapshot.messages if snapshot is not None else session.messages
        return session.get_messages(attachment_store, messages=messages)

    # -- persistence internals ---------------------------------------------

    def _session_dir(self, session_id: str) -> Path:
        safe_session_id = validate_session_id(session_id)
        storage_root = self._storage_dir.resolve()
        path = (storage_root / safe_session_id).resolve()
        try:
            path.relative_to(storage_root)
        except ValueError:
            raise InvalidPathError(f"Path outside storage root: {path}")
        return path

    def _legacy_session_path(self, session_id: str) -> Path:
        safe_session_id = validate_session_id(session_id)
        storage_root = self._storage_dir.resolve()
        path = (storage_root / f"{safe_session_id}.json").resolve()
        try:
            path.relative_to(storage_root)
        except ValueError:
            raise InvalidPathError(f"Path outside storage root: {path}")
        return path

    def _manifest_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "manifest.json"

    def _conversation_path(self, session_id: str, conversation_id: str) -> Path:
        safe_conversation_id = validate_conversation_id(conversation_id)
        session_dir = self._session_dir(session_id)
        conversations_dir = (session_dir / "conversations").resolve()
        path = (conversations_dir / f"{safe_conversation_id}.json").resolve()
        try:
            path.relative_to(session_dir)
        except ValueError:
            raise InvalidPathError(f"Path outside session dir: {path}")
        return path

    def _persist(self, session: Session) -> None:
        session_dir = self._session_dir(session.id)
        conversations_dir = session_dir / "conversations"
        manifest_path = session_dir / "manifest.json"
        conversation = session.to_conversation_record()
        conversation_path = self._conversation_path(session.id, conversation.id)

        try:
            conversations_dir.mkdir(parents=True, exist_ok=True)
            conversation_path.write_text(
                json.dumps(
                    conversation.to_file_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            manifest_path.write_text(
                json.dumps(
                    session.to_manifest_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.branch_cache.set(
                (session.id, session.active_conversation_id),
                lineage=session.branch_lineage(),
                branch_fingerprint=session.branch_fingerprint(),
                messages=session.messages,
            )
        except Exception:
            logger.exception("Failed to persist session %s", session.id)

    def _delete_file(self, session_id: str) -> None:
        try:
            session_dir = self._session_dir(session_id)
            if session_dir.exists():
                self._remove_tree(session_dir)
            legacy_path = self._legacy_session_path(session_id)
            if legacy_path.exists():
                legacy_path.unlink()
        except Exception:
            logger.exception("Failed to delete session file %s", session_id)

    def _load_all(self) -> None:
        """Load session manifests and legacy JSON files from disk on startup."""
        count = 0
        for manifest_path in self._storage_dir.glob("*/manifest.json"):
            try:
                session = self._load_manifest_session(manifest_path)
                if session is None:
                    continue
                self._sessions[session.id] = session
                self.get_active_branch_snapshot(session.id)
                count += 1
            except InvalidSessionIdError:
                logger.warning(
                    "Skipping session manifest with unsafe id: %s",
                    manifest_path,
                )
            except Exception:
                logger.exception("Failed to load session manifest %s", manifest_path)

        for path in self._storage_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                session = Session.from_dict(data, vault_path=self._vault_path)
                validate_session_id(session.id)
                if path.name != f"{session.id}.json":
                    logger.warning(
                        "Skipping session file %s because its embedded id is %s",
                        path.name,
                        session.id,
                    )
                    continue
                if session.id in self._sessions:
                    continue
                self._sessions[session.id] = session
                self._persist(session)
                count += 1
            except InvalidSessionIdError:
                logger.warning("Skipping session file with unsafe id: %s", path.name)
            except Exception:
                logger.exception("Failed to load session file %s", path.name)

        if count:
            logger.info("Loaded %d sessions from %s", count, self._storage_dir)

    def _load_manifest_session(self, manifest_path: Path) -> Session | None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        session_id = validate_session_id(str(manifest.get("id") or ""))
        if manifest_path.parent.name != session_id:
            logger.warning(
                "Skipping manifest %s because its embedded id is %s",
                manifest_path,
                session_id,
            )
            return None

        active_conversation_id = validate_conversation_id(
            str(manifest.get("active_conversation_id") or ROOT_CONVERSATION_ID)
        )
        conversation_index = self._load_conversation_index(manifest, session_id)

        # Gracefully handle a corrupt active-conversation file: fall back to an
        # empty conversation so the session can still be loaded from memory.
        try:
            conversation_data = self._read_conversation_file(
                session_id,
                active_conversation_id,
            )
        except Exception:
            logger.warning(
                "Failed to read active conversation %s for session %s; using empty conversation",
                active_conversation_id,
                session_id,
            )
            conversation_data = {"messages": [], "id": active_conversation_id}

        conversation = ConversationRecord.from_file_dict(
            conversation_data,
            session_id=session_id,
        )
        conversation_index[conversation.id] = ConversationRecord(
            id=conversation.id,
            session_id=conversation.session_id,
            parent_id=conversation.parent_id,
            fork_message_id=conversation.fork_message_id,
            revision=conversation.revision,
            created_at=conversation.created_at,
            last_activity_at=conversation.last_activity_at,
            title=conversation.title,
            persisted_message_count=conversation.message_count,
        )
        session = Session.from_manifest_and_conversation(
            manifest,
            conversation,
            conversation_index,
            vault_path=self._vault_path,
        )
        session.messages = self._materialize_branch_from_disk(session)
        return session

    def _load_conversation_index(
        self,
        manifest: dict[str, Any],
        session_id: str,
    ) -> dict[str, ConversationRecord]:
        raw_conversations = manifest.get("conversations", {})
        if not isinstance(raw_conversations, dict):
            return {}

        conversation_index: dict[str, ConversationRecord] = {}
        for conversation_id, raw_record in raw_conversations.items():
            if not isinstance(raw_record, dict):
                continue
            record_data = dict(raw_record)
            record_data.setdefault("id", conversation_id)
            record_data.setdefault("session_id", session_id)
            record = ConversationRecord.from_manifest_dict(record_data)
            if record.session_id != session_id:
                logger.warning(
                    "Skipping conversation %s because its session id is %s",
                    record.id,
                    record.session_id,
                )
                continue
            conversation_index[record.id] = record
        return conversation_index

    def _read_conversation_file(
        self,
        session_id: str,
        conversation_id: str,
    ) -> dict[str, Any]:
        path = self._conversation_path(session_id, conversation_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _materialize_branch_from_disk(
        self,
        session: Session,
        conversation_id: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            materialized: list[dict[str, Any]] = []
            target_conversation_id = conversation_id or session.active_conversation_id
            for lineage_conversation_id in session.branch_lineage(
                target_conversation_id
            ):
                data = self._read_conversation_file(
                    session.id,
                    lineage_conversation_id,
                )
                conversation = ConversationRecord.from_file_dict(
                    data,
                    session_id=session.id,
                )
                record = session.conversation_index.get(lineage_conversation_id)
                fork_message_id = (
                    record.fork_message_id if record is not None else None
                )
                if fork_message_id:
                    materialized = self._truncate_after_message(
                        materialized,
                        fork_message_id,
                    )
                materialized.extend(_clone_messages(conversation.messages))
            return materialized
        except Exception:
            logger.exception(
                "Failed to materialize active branch for session %s; using memory",
                session.id,
            )
            return _clone_messages(session.messages)

    def _truncate_after_message(
        self,
        messages: list[dict[str, Any]],
        fork_message_id: str,
    ) -> list[dict[str, Any]]:
        for index, message in enumerate(messages):
            if message.get("message_id") == fork_message_id:
                return messages[: index + 1]
        return messages

    def _require_session(self, session_id: str) -> Session:
        safe_session_id = validate_session_id(session_id)
        session = self._sessions.get(safe_session_id)
        if session is None:
            raise KeyError(f"Session {safe_session_id} not found")
        return session

    def _find_message_index(
        self,
        messages: list[dict[str, Any]],
        message_id: str,
    ) -> int | None:
        for index, message in enumerate(messages):
            if message.get("message_id") == message_id:
                return index
        return None

    def _new_conversation_id(self, session: Session) -> str:
        for _ in range(100):
            conversation_id = f"c_{uuid.uuid4().hex[:12]}"
            if conversation_id not in session.conversation_index:
                return conversation_id
        raise RuntimeError("Failed to allocate a conversation id")

    def _remove_tree(self, root: Path) -> None:
        storage_root = self._storage_dir.resolve()
        resolved = root.resolve()
        try:
            resolved.relative_to(storage_root)
        except ValueError:
            raise InvalidPathError(f"Path outside storage root: {resolved}")
        for path in sorted(resolved.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if path.is_symlink():
                path.unlink()
            elif path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        resolved.rmdir()
