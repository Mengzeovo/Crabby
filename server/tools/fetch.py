"""Fetch tool — 获取 URL 网页内容并转为 Markdown。

适用于让大模型阅读网上的参考资料、文档或最新的新闻，
替代缺失的大脑知识。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify
from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult


# 允许的最大跳转次数（手动跟随，每跳都重新做一次目标安全检查）
MAX_REDIRECTS = 5


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True iff the address is a routable public address.

    Rejects loopback, link-local, private, multicast, reserved, unspecified.
    """
    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_url_target(url: str) -> str | None:
    """Return an error message if ``url`` should not be fetched, else None.

    Blocks:
      - Non-http(s) schemes (file://, ftp://, gopher://, javascript:, ...)
      - Hostnames that resolve to loopback / private / link-local IPs
      - Hostnames given as raw private/loopback IPs (no DNS round-trip skipped)
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"不允许的协议：{parsed.scheme or '<missing>'}（仅支持 http/https）"

    host = parsed.hostname
    if not host:
        return "URL 缺少主机名。"

    # If the hostname is already a literal IP, validate it directly.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if not _is_public_ip(literal):
            return f"目标 IP 不允许：{host}（loopback / 私网 / 保留段）"
        return None

    # Otherwise resolve all addresses and reject if any are non-public.
    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        return f"无法解析主机名 {host}: {exc}"

    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        addr = sockaddr[0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not _is_public_ip(ip):
            return f"目标主机解析到不允许的 IP：{host} → {addr}"

    return None


class FetchInput(BaseModel):
    """Fetch 工具的输入参数。"""

    url: str = Field(description="The URL to fetch content from (e.g. 'https://example.com/docs')")
    prompt: str = Field(
        default="",
        description="Optional prompt or objective for why you are fetching this content. This will be included in the tool logs.",
    )


class FetchTool(Tool):
    """获取指定 URL 网页内容并转换为 Markdown 的工具。

    专门用于给 Agent 提供外网信息差。
    如果返回内容超长会自动截断。

    安全保障：
    - 仅允许 http/https
    - 拒绝指向 loopback / 私网 / 保留段的目标（防 SSRF）
    - 手动跟随跳转，每跳都重新校验目标
    """

    name = "fetch"
    description = (
        "获取网络上的 URL 内容并自动转换为 Markdown 格式供你阅读。\n"
        "仅支持静态或基础网页，且仅可访问公网地址。"
    )
    input_schema = FetchInput
    is_read_only = True
    max_result_chars = 100_000

    async def call(self, params: BaseModel, ctx: Context) -> ToolResult:
        """执行网络请求与转换操作。"""
        assert isinstance(params, FetchInput)

        # 为了应对一些反爬虫以及更友好的请求，我们加上常见的 User-Agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        try:
            current_url = params.url
            # 手动跟随跳转：每跳都重新校验目标，防止跳到内网
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                response: httpx.Response | None = None
                for _ in range(MAX_REDIRECTS + 1):
                    err = _validate_url_target(current_url)
                    if err:
                        return ToolResult(
                            output=f"抓取失败: {err}",
                            metadata={"error": True, "error_type": "url_validation", "url": current_url},
                        )

                    response = await client.get(current_url, headers=headers)
                    if response.is_redirect:
                        next_url = response.headers.get("location")
                        if not next_url:
                            break
                        # 解析相对跳转
                        current_url = str(httpx.URL(current_url).join(next_url))
                        continue
                    break
                else:
                    return ToolResult(
                        output=f"抓取失败: 超过最大跳转次数 ({MAX_REDIRECTS})",
                        metadata={"error": True, "error_type": "too_many_redirects", "url": params.url},
                    )

                if response is None:
                    return ToolResult(
                        output="抓取失败: 未收到响应。",
                        metadata={"error": True, "error_type": "empty_response", "url": params.url},
                    )
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")

                if "application/json" in content_type:
                    # 如果是 JSON
                    text = response.text
                elif "text/" in content_type:
                    # 如果是 HTML，提取文本
                    soup = BeautifulSoup(response.text, "html.parser")
                    # 移除多余的 JS, CSS 等空壳
                    for script in soup(["script", "style", "noscript", "meta", "link"]):
                        script.decompose()

                    html_content = str(soup)
                    text = markdownify(html_content, heading_style="ATX")
                else:
                    return ToolResult(
                        output=f"抓取失败: 不支持的 Content-Type ({content_type})，仅支持提取文本或 HTML 内容。",
                        metadata={
                            "error": True,
                            "error_type": "unsupported_content_type",
                            "content_type": content_type,
                            "url": current_url,
                        },
                    )

                # 清洗换行
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                text = "\n".join(lines)

                if not text:
                    return ToolResult(output="网页抓取成功，但未解析出有效的文本内容。")

                if len(text) > self.max_result_chars:
                    text = text[: self.max_result_chars] + f"\n\n[Warning: 内容已超长截断，当前展示至 {self.max_result_chars} 字符]"

                return ToolResult(
                    output=f"### 来源 URL: {current_url}\n\n{text}",
                    metadata={"url": current_url, "chars": len(text)},
                )

        except httpx.HTTPStatusError as e:
            return ToolResult(
                output=f"HTTP 请求失败：状态码 {e.response.status_code}",
                metadata={
                    "error": True,
                    "error_type": "http_status",
                    "status_code": e.response.status_code,
                    "url": str(e.request.url),
                },
            )
        except httpx.RequestError as e:
            return ToolResult(
                output=f"请求 URL 失败: {str(e)}",
                metadata={"error": True, "error_type": "request", "url": params.url},
            )
        except Exception as e:
            return ToolResult(
                output=f"执行 Fetch 时出现未知错误: {str(e)}",
                metadata={"error": True, "error_type": "unexpected", "url": params.url},
            )
