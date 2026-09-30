"""采集失败恢复契约；同时覆盖独立服务和后端兼容适配器。"""

import importlib
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "writter_back"))


@pytest.fixture(params=["research_service", "infrastructure.research"])
def modules(request):
    name = request.param
    return importlib.import_module(f"{name}.biquge"), importlib.import_module(f"{name}.sampling")


@pytest.mark.asyncio
async def test_failed_catalog_uses_remaining_source_once(modules):
    adapter_module, sampling = modules
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if not request.url.query:
            return httpx.Response(520)
        return httpx.Response(200, headers={"content-type": "text/html"},
                             text="<a href='/novel/1.html'>样本甲</a>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = adapter_module.BiqugeCatalogAdapter(
            client, adapter_module.BiqugeFetchPolicy(min_interval_seconds=0, max_retries=0)
        )
        result = await adapter.fetch_strata(
            "女频", {"popular": ["/lists/48.html", "/lists/48.html?page=2"],
                     "recent": ["/lists/48.html"]},
            sampling.SampleQuota.from_total(6), allow_shortage=True,
        )
    assert len(result) == 1
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [403, 429])
async def test_blocked_catalog_never_tries_backup(modules, status):
    adapter_module, _ = modules
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = adapter_module.BiqugeCatalogAdapter(client)
        with pytest.raises(adapter_module.BiqugeBlockedError):
            await adapter.fetch_strata(
                "女频", {"popular": ["/lists/48.html", "/lists/48.html?page=2"]}
            )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_all_failed_catalogs_keep_stage_url_and_status(modules):
    adapter_module, _ = modules
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(520))
    ) as client:
        adapter = adapter_module.BiqugeCatalogAdapter(
            client, adapter_module.BiqugeFetchPolicy(min_interval_seconds=0, max_retries=0)
        )
        with pytest.raises(adapter_module.BiqugeResearchError) as failure:
            await adapter.fetch_strata("女频", {"popular": ["/lists/48.html"]})
    assert "/lists/48.html" in str(failure.value)
    assert "来源目录暂不可用：HTTP 520" in str(failure.value)


def test_optional_candidate_pool_does_not_require_spares(modules):
    adapter_module, sampling = modules
    candidate = adapter_module.CatalogCandidate(
        url="https://www.biquge.pro/novel/1.html", title="样本甲",
        source_category="女频", bucket="popular", rank=1,
    )
    quota = sampling.SampleQuota.from_total(6)
    assert sampling.select_stratified_candidates(
        [candidate, candidate], "女频", quota, allow_shortage=True
    ) == (candidate,)
    with pytest.raises(sampling.SamplingShortageError):
        sampling.select_stratified_candidates([candidate], "女频", quota)
    with pytest.raises(sampling.SamplingShortageError):
        sampling.select_stratified_candidates([], "女频", quota, allow_shortage=True)


def test_zero_quota_never_consumes_candidate(modules):
    adapter_module, sampling = modules
    candidates = [
        adapter_module.CatalogCandidate(
            url=f"https://www.biquge.pro/novel/{index}.html", title=f"样本{index}",
            source_category="女频", bucket=bucket, rank=index,
        )
        for index, bucket in enumerate(("popular", "new", "recent"), 1)
    ]
    result = sampling.select_stratified_candidates(
        candidates, "女频", sampling.SampleQuota(popular=0, new=0, recent=1)
    )
    assert result == (candidates[2],)


def test_remaining_candidates_follow_priority_pool_without_duplicates(modules):
    adapter_module, sampling = modules
    candidates = [
        adapter_module.CatalogCandidate(
            url=f"https://www.biquge.pro/novel/{index}.html", title=f"样本{index}",
            source_category="女频", bucket="popular", rank=index,
        )
        for index in range(1, 8)
    ]
    result = sampling.select_stratified_candidates(
        candidates + candidates, "女频", sampling.SampleQuota.from_total(2),
        allow_shortage=True, include_remaining=True,
    )
    assert result == tuple(candidates)
    assert len({item.url for item in result}) == 7
