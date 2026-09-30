"""Tavily检索适配器；仅发送显式短主题词，不上传私有上下文。"""

from datetime import datetime, timezone

import httpx

from application.creative.errors import CreativePause
from service.value_objects.creative import ResearchSource


class TavilyResearchAdapter:
    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None):
        self.api_key, self.client = api_key, client

    async def search(self, query: str) -> list[ResearchSource]:
        """执行单次固定地址检索，禁止任意URL抓取与隐式重试。"""
        if not query.strip() or len(query) > 120:
            raise ValueError("只允许1-120字符的必要主题检索")
        if not self.api_key:
            raise CreativePause("research_unavailable", "缺少Tavily配置；请提供关键资料或配置检索服务")
        payload = {
            "query": query, "max_results": 3, "search_depth": "basic",
            "include_answer": False, "include_raw_content": False,
        }
        if self.client is not None:
            response = await self._request(self.client, payload)
        else:
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await self._request(client, payload)
        return [_source(item) for item in response.get("results", [])[:3] if item.get("content") and item.get("url")]

    async def _request(self, client, payload):
        response = await client.post(
            "https://api.tavily.com/search", json=payload,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        response.raise_for_status()
        return response.json()


def _source(item: dict) -> ResearchSource:
    return ResearchSource(
        title=str(item.get("title") or "检索资料")[:240], text=str(item["content"])[:50000],
        category="market_observation", origin="tavily", source_url=item["url"],
        observed_at=datetime.now(timezone.utc),
        applicable_scope="待核实的网页观察；搜索结果不等于事实或市场表现证明",
    )


def decode_source_file(filename: str, content: bytes) -> str:
    """资料上传仅支持UTF-8 TXT/Markdown，读取后仍执行字符上限。"""
    if not filename.lower().endswith((".txt", ".md", ".markdown")):
        raise ValueError("仅支持TXT和Markdown资料")
    if len(content) > 200003:
        raise ValueError("资料文件过大")
    text = content.decode("utf-8-sig")
    if not text.strip() or len(text) > 50000:
        raise ValueError("每份资料必须为1-50000字符")
    return text
