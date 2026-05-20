"""Regression tests for fetch tool's SSRF protection."""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.base import Context
from tools.fetch import FetchInput, FetchTool, _validate_url_target


class TestValidateUrlTarget:
    def test_rejects_non_http_scheme(self):
        assert _validate_url_target("file:///etc/passwd") is not None
        assert _validate_url_target("ftp://example.com/x") is not None
        assert _validate_url_target("javascript:alert(1)") is not None

    def test_rejects_loopback_literal(self):
        assert _validate_url_target("http://127.0.0.1:8000/admin") is not None
        assert _validate_url_target("http://[::1]/x") is not None

    def test_rejects_private_ipv4_literal(self):
        for host in ("10.0.0.1", "172.16.0.1", "192.168.1.1"):
            assert _validate_url_target(f"http://{host}/x") is not None, host

    def test_rejects_link_local_metadata(self):
        # AWS / GCP / Azure metadata endpoint
        assert _validate_url_target("http://169.254.169.254/latest/meta-data/") is not None

    def test_accepts_public_literal(self):
        # 1.1.1.1 is a public Cloudflare DNS — should pass
        assert _validate_url_target("https://1.1.1.1/") is None

    def test_rejects_localhost_hostname(self, monkeypatch: pytest.MonkeyPatch):
        # Make getaddrinfo deterministic — pretend "localhost" resolves to 127.0.0.1
        import socket
        def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 0))]
        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert _validate_url_target("http://localhost/x") is not None

    def test_accepts_resolvable_public_hostname(self, monkeypatch: pytest.MonkeyPatch):
        import socket
        def fake_getaddrinfo(host, port, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 0))]
        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
        assert _validate_url_target("https://example.com/") is None


class TestFetchToolBlocksSsrf:
    async def test_call_rejects_loopback_before_request(self, tmp_path: Path):
        tool = FetchTool()
        result = await tool.call(
            FetchInput(url="http://127.0.0.1:8000/admin"),
            Context(vault_path=tmp_path),
        )
        assert "抓取失败" in result.output
        assert "127.0.0.1" in result.output or "loopback" in result.output.lower() or "私网" in result.output

    async def test_call_rejects_metadata_endpoint(self, tmp_path: Path):
        tool = FetchTool()
        result = await tool.call(
            FetchInput(url="http://169.254.169.254/latest/meta-data/"),
            Context(vault_path=tmp_path),
        )
        assert "抓取失败" in result.output

    async def test_call_rejects_unsupported_scheme(self, tmp_path: Path):
        tool = FetchTool()
        result = await tool.call(
            FetchInput(url="file:///etc/passwd"),
            Context(vault_path=tmp_path),
        )
        assert "抓取失败" in result.output
        assert "协议" in result.output or "scheme" in result.output.lower()
