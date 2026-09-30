import httpx
import pytest

from research_service.biquge import BiqugeCatalogAdapter, BiqugeFetchPolicy, BiqugeResearchError
from research_service.sampling import SampleQuota


@pytest.mark.asyncio
async def test_520_retries_without_honoring_sticky_retry_delay() -> None:
    statuses = iter((520, 200, 200))

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        headers = {"content-type": "text/html; charset=utf-8"}
        if status == 520:
            headers["retry-after"] = "60"
        return httpx.Response(status, headers=headers, text="<html></html>", request=request)

    now = [0.0]
    delays = []

    async def sleep(delay: float) -> None:
        delays.append(delay)
        now[0] += delay

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BiqugeCatalogAdapter(
        client=client,
        policy=BiqugeFetchPolicy(min_interval_seconds=1, max_retries=1),
        sleep=sleep,
        clock=lambda: now[0],
    )
    source = await adapter._request_text("/novel/1.html", "detail")
    await adapter._request_text("/lists/51.html", "catalog")
    assert source == "<html></html>"
    assert delays == [1.0, 1.0]
    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_520_retry_backoff_is_bounded_before_domain_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            520,
            headers={"content-type": "text/html; charset=utf-8", "retry-after": "60"},
            text="<html></html>",
            request=request,
        )

    delays = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BiqugeCatalogAdapter(
        client=client,
        policy=BiqugeFetchPolicy(min_interval_seconds=0, max_retries=4),
        sleep=sleep,
    )
    with pytest.raises(BiqugeResearchError, match="HTTP 520"):
        await adapter._request_text("/novel/1.html", "detail")
    assert calls == 5
    assert delays == [1.0, 2.0, 4.0, 4.0]
    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_strata_reuses_one_catalog_response_for_three_buckets() -> None:
    source = """
    <a href='/novel/1.html'><img></a><a href='/novel/1.html'>热门甲</a>
    <h2>最近更新小说列表</h2><a href='/novel/2.html'>最近乙</a>
    <h2>最新入库小说</h2><a href='/novel/3.html'>新书丙</a>
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"},
            text=source, request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = BiqugeCatalogAdapter(
        client=client, policy=BiqugeFetchPolicy(min_interval_seconds=0)
    )
    result = await adapter.fetch_strata(
        "科幻",
        {"popular": ["/lists/51.html"], "new": ["/lists/51.html"], "recent": ["/lists/51.html"]},
        SampleQuota(popular=1, new=1, recent=1),
    )
    assert len(result) == 3
    assert calls == 1
    await adapter.close()
    await client.aclose()
