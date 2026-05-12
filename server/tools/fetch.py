"""Fetch tool — 获取 URL 网页内容并转为 Markdown。

适用于让大模型阅读网上的参考资料、文档或最新的新闻，
替代缺失的大脑知识。
"""

from __future__ import annotations

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify
from pydantic import BaseModel, Field

from tools.base import Context, Tool, ToolResult


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
    """

    name = "fetch"
    description = (
        "获取网络上的 URL 内容并自动转换为 Markdown 格式供你阅读。\n"
        "仅支持静态或基础网页。这极大增强了你获取最新信息和查阅官方文档的能力。"
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
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(params.url, headers=headers)
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
                    return ToolResult(output=f"抓取失败: 不支持的 Content-Type ({content_type})，仅支持提取文本或 HTML 内容。")
                
                # 清洗换行
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                text = "\n".join(lines)
                
                if not text:
                    return ToolResult(output="网页抓取成功，但未解析出有效的文本内容。")
                
                if len(text) > self.max_result_chars:
                    text = text[:self.max_result_chars] + f"\n\n[Warning: 内容已超长截断，当前展示至 {self.max_result_chars} 字符]"
                    
                return ToolResult(
                    output=f"### 来源 URL: {params.url}\n\n{text}",
                    metadata={"url": params.url, "chars": len(text)}
                )
                
        except httpx.HTTPStatusError as e:
            return ToolResult(output=f"HTTP 请求失败：状态码 {e.response.status_code}")
        except httpx.RequestError as e:
            return ToolResult(output=f"请求 URL 失败: {str(e)}")
        except Exception as e:
            return ToolResult(output=f"执行 Fetch 时出现未知错误: {str(e)}")
