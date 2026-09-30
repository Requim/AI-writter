import httpx
import pytest

from infrastructure.research.biquge import (
    BiqugeBlockedError,
    BiqugeCatalogAdapter,
    BiqugeFetchPolicy,
    BiqugeResearchError,
    OpeningAuthorizationError,
)


def _transport(body: str, status: int = 200) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8"}, text=body)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_opening_requires_explicit_authorization() -> None:
    client = httpx.AsyncClient(transport=_transport("<html></html>"))
    adapter = BiqugeCatalogAdapter(client=client)
    with pytest.raises(OpeningAuthorizationError):
        await adapter.fetch_opening("/book/500/one.html")
    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_blocked_response_is_not_retried_or_bypassed() -> None:
    client = httpx.AsyncClient(transport=_transport("blocked", 429))
    adapter = BiqugeCatalogAdapter(client=client, policy=BiqugeFetchPolicy(max_retries=2))
    with pytest.raises(BiqugeBlockedError):
        await adapter.fetch_catalog("/lists/51.html", "科幻")
    await adapter.close()
    await client.aclose()


@pytest.mark.asyncio
async def test_analyze_opening_discards_transient_body() -> None:
    fixture = "<h1 id='chapterTitle'>第1章 测试</h1><script>var x={content:'<p>出现异常。</p>'}</script>"
    client = httpx.AsyncClient(transport=_transport(fixture))
    adapter = BiqugeCatalogAdapter(client=client, policy=BiqugeFetchPolicy(min_interval_seconds=0))
    captured = []

    async def analyzer(opening):
        captured.append(opening.text)
        return opening.metrics.character_count

    result = await adapter.analyze_opening("/book/500/one.html", analyzer, authorized=True)
    assert result > 0 and captured
    await adapter.close()
    await client.aclose()


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
