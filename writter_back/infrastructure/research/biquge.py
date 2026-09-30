"""笔趣阁受限研究适配器；默认不读取首章正文。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Awaitable, Callable

import httpx

from infrastructure.research.biquge_parser import (
    TransientOpeningInput,
    canonical_source_url,
    parse_catalog_page,
    parse_detail_page,
    parse_opening_page,
)
from infrastructure.research.sampling import SampleQuota, select_stratified_candidates
from service.value_objects.novel_research import CatalogCandidate, ChapterIndex, NovelMetadata


def _retry_delay(attempt: int) -> float:
    return float(2 ** min(attempt, 2))


class BiqugeResearchError(RuntimeError):
    """研究请求或解析失败。"""


class BiqugeBlockedError(BiqugeResearchError):
    """来源返回拒绝或限流，适配器不得绕过。"""


class OpeningAuthorizationError(BiqugeResearchError):
    """没有明确授权时禁止读取首章正文。"""


@dataclass(frozen=True)
class BiqugeFetchPolicy:
    min_interval_seconds: float = 1.0
    max_requests: int = 200
    timeout_seconds: float = 15.0
    max_retries: int = 2
    max_response_bytes: int = 2_000_000
    user_agent: str = "AI-writter-research/1.0"

    def __post_init__(self) -> None:
        if self.min_interval_seconds < 0 or self.max_requests < 1:
            raise ValueError("请求间隔和请求上限必须为非负/正数")
        if self.timeout_seconds <= 0 or self.max_retries < 0 or self.max_response_bytes < 1:
            raise ValueError("超时、重试次数和响应上限配置无效")


class BiqugeCatalogAdapter:
    """公开目录研究入口；不记录响应正文，也不自动跟随外部重定向。"""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        policy: BiqugeFetchPolicy | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.policy = policy or BiqugeFetchPolicy()
        self._client = client or httpx.AsyncClient(
            timeout=self.policy.timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": self.policy.user_agent},
        )
        self._owns_client = client is None
        self._sleep, self._clock = sleep, clock
        self._request_count, self._last_request = 0, float("-inf")

    async def __aenter__(self) -> "BiqugeCatalogAdapter":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def fetch_catalog(self, url: str, category: str, bucket: str = "fallback") -> list[CatalogCandidate]:
        source = await self._request_text(url, "catalog")
        return parse_catalog_page(source, category, bucket)

    async def fetch_detail(self, url: str, fallback_category: str = "其他") -> tuple[NovelMetadata, ChapterIndex]:
        source = await self._request_text(url, "detail")
        return parse_detail_page(source, url, fallback_category)

    async def fetch_strata(
        self,
        category: str,
        sources: dict[str, list[str]],
        quota: SampleQuota = SampleQuota(),
        *,
        allow_shortage: bool = False,
        include_remaining: bool = False,
    ) -> tuple[CatalogCandidate, ...]:
        """按调用方提供的榜单/新书/更新页采集候选，再执行确定性抽样。"""
        candidates: list[CatalogCandidate] = []
        pages, failures = await self._fetch_catalog_pages(sources)
        entries = ((bucket, url) for bucket, urls in sources.items() for url in urls)
        for bucket, url in entries:
            source = pages.get(canonical_source_url(url, "catalog"))
            if source is not None:
                candidates.extend(parse_catalog_page(source, category, bucket))
        if not candidates and failures:
            raise BiqugeResearchError("; ".join(failures)[:1000])
        return select_stratified_candidates(
            candidates, category, quota, allow_shortage=allow_shortage,
            include_remaining=include_remaining,
        )

    async def _fetch_catalog_pages(self, sources: dict[str, list[str]]):
        urls = dict.fromkeys(
            canonical_source_url(url, "catalog")
            for values in sources.values() for url in values
        )
        pages: dict[str, str] = {}
        failures: list[str] = []
        for url in urls:
            try:
                pages[url] = await self._request_text(url, "catalog")
            except BiqugeBlockedError:
                raise
            except (BiqugeResearchError, httpx.HTTPStatusError) as exc:
                failures.append(f"{url}: {exc}")
        return pages, failures

    async def fetch_opening(self, url: str, authorized: bool = False) -> TransientOpeningInput:
        """只有调用方明确传入授权标记时才允许临时读取首章。"""
        if not authorized:
            raise OpeningAuthorizationError("未提供首章正文处理授权")
        source = await self._request_text(url, "chapter")
        return parse_opening_page(source, url)

    async def analyze_opening(
        self,
        url: str,
        analyzer: Callable[[TransientOpeningInput], Awaitable[object]],
        authorized: bool = False,
    ) -> object:
        opening = await self.fetch_opening(url, authorized=authorized)
        try:
            return await analyzer(opening)
        finally:
            opening.discard()

    async def _request_text(self, url: str, kind: str) -> str:
        normalized = canonical_source_url(url, kind)
        for attempt in range(self.policy.max_retries + 1):
            await self._reserve_request()
            try:
                response = await self._client.get(normalized)
            except httpx.RequestError as exc:
                if attempt >= self.policy.max_retries:
                    raise BiqugeResearchError("来源请求失败") from exc
                await self._sleep(_retry_delay(attempt))
                continue
            if response.status_code in {403, 429}:
                raise BiqugeBlockedError(f"来源拒绝或限流：HTTP {response.status_code}")
            if response.status_code >= 500:
                if attempt < self.policy.max_retries:
                    await self._sleep(_retry_delay(attempt))
                    continue
                page = {"catalog": "目录", "detail": "详情", "chapter": "章节"}.get(kind, "页面")
                raise BiqugeResearchError(f"来源{page}暂不可用：HTTP {response.status_code}")
            if 300 <= response.status_code < 400:
                raise BiqugeResearchError("来源重定向未被允许")
            response.raise_for_status()
            if len(response.content) > self.policy.max_response_bytes:
                raise BiqugeResearchError("来源响应超过大小上限")
            if response.history or canonical_source_url(str(response.url), kind) != normalized:
                raise BiqugeResearchError("来源重定向终点未被允许")
            if "text/html" not in response.headers.get("content-type", "").lower():
                raise BiqugeResearchError("来源响应不是 HTML")
            return response.text
        raise BiqugeResearchError("来源请求重试耗尽")

    async def _reserve_request(self) -> None:
        if self._request_count >= self.policy.max_requests:
            raise BiqugeResearchError("已达到本次研究请求上限")
        elapsed = self._clock() - self._last_request
        if elapsed < self.policy.min_interval_seconds:
            await self._sleep(self.policy.min_interval_seconds - elapsed)
        self._last_request = self._clock()
        self._request_count += 1
