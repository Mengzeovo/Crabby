"""Regression tests for ConnectionManager identity-based disconnect.

Pre-fix bug: ``disconnect(session_id)`` always pop()'d the entry by key.
When the same session reconnected (entry overwritten by the new WS), the
*old* WS's finally-block would later pop the NEW WS's entry, silently
killing notifications for the new tab.
Fix: ``disconnect(session_id, ws)`` only removes the entry if it matches
the given WS object (identity check).
"""
from __future__ import annotations

from api.websocket import ConnectionManager


class _FakeWS:
    """Minimal stand-in for fastapi.WebSocket — identity-comparable."""

    def __init__(self, label: str) -> None:
        self.label = label

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"_FakeWS({self.label})"


def test_disconnect_with_identity_check_does_not_evict_replacement():
    mgr = ConnectionManager()
    ws_old = _FakeWS("old")
    ws_new = _FakeWS("new")

    mgr.connect("session-1", ws_old)
    # Reconnect: the new WS replaces the old entry.
    mgr.connect("session-1", ws_new)
    assert mgr.active_connections["session-1"] is ws_new

    # Old WS's finally-block now fires. With identity check, it must NOT
    # remove the new WS's entry.
    mgr.disconnect("session-1", ws_old)
    assert mgr.active_connections.get("session-1") is ws_new


def test_disconnect_without_ws_keeps_legacy_pop_behavior():
    """Calling disconnect() without a ws should still pop the entry."""
    mgr = ConnectionManager()
    ws = _FakeWS("only")
    mgr.connect("session-1", ws)

    mgr.disconnect("session-1")
    assert "session-1" not in mgr.active_connections


def test_disconnect_matching_ws_removes_entry():
    mgr = ConnectionManager()
    ws = _FakeWS("only")
    mgr.connect("session-1", ws)

    mgr.disconnect("session-1", ws)
    assert "session-1" not in mgr.active_connections


def test_disconnect_unknown_session_is_noop():
    mgr = ConnectionManager()
    ws = _FakeWS("ghost")
    # Should not raise
    mgr.disconnect("never-connected", ws)
    assert "never-connected" not in mgr.active_connections
