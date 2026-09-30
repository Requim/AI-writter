import pytest

from research_service.batch_runner import ResearchBatchRunner
from research_service.biquge import BiqugeResearchError
from research_service.contracts import BatchRequest, CatalogCandidate


class _Repository:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []

    async def update_job(self, _job_id: str, **changes: object) -> None:
        self.updates.append(changes)


class _Adapter:
    def __init__(self, count: int) -> None:
        self.candidates = tuple(
            CatalogCandidate(
                url=f"https://www.biquge.pro/novel/{index}.html",
                title=f"样本{index}",
                source_category="玄幻",
                bucket="popular",
                rank=index,
            )
            for index in range(1, count + 1)
        )

    async def fetch_strata(self, *_args: object, **_kwargs: object) -> tuple[CatalogCandidate, ...]:
        assert _kwargs["allow_shortage"] is True
        assert _kwargs["include_remaining"] is True
        return self.candidates


class _Runner(ResearchBatchRunner):
    def __init__(self, repository: _Repository, outcomes: list[bool | Exception]) -> None:
        super().__init__(repository, object(), summarizer=object())  # type: ignore[arg-type]
        self.outcomes = iter(outcomes)

    async def _collect_candidate(self, *_args: object) -> bool:
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _request(target: int) -> BatchRequest:
    return BatchRequest(
        batch_id="batch-1",
        categories=("玄幻",),
        sample_target_per_category=target,
        sources={"玄幻": {"popular": ("https://www.biquge.pro/lists/42.html",)}},
    )


@pytest.mark.asyncio
async def test_category_uses_later_candidate_after_transient_failure() -> None:
    repository = _Repository()
    runner = _Runner(repository, [BiqugeResearchError("来源详情暂不可用：HTTP 520"), True])

    processed, failures = await runner._run_category(
        _Adapter(2), _request(1), "玄幻", 0, "job-1"
    )

    assert processed == 1
    assert failures == []
    assert repository.updates[-1] == {"processed": 1}


@pytest.mark.asyncio
async def test_category_reports_520_when_candidates_cannot_fill_target() -> None:
    repository = _Repository()
    runner = _Runner(
        repository,
        [
            BiqugeResearchError("来源详情暂不可用：HTTP 520"),
            BiqugeResearchError("来源详情暂不可用：HTTP 520"),
        ],
    )

    processed, failures = await runner._run_category(
        _Adapter(2), _request(1), "玄幻", 0, "job-1"
    )

    assert processed == 0
    assert len(failures) == 1
    assert "仅新增 0/1 个样本" in failures[0]
    assert "HTTP 520" in failures[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcomes", "status", "processed"),
    [([True, True], "completed", 2), ([True, False], "partial", 1),
     ([False, False], "failed", 0)],
)
async def test_terminal_phase_matches_actual_result(monkeypatch, outcomes, status, processed):
    class Adapter(_Adapter):
        def __init__(self):
            super().__init__(2)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            pass

    monkeypatch.setattr("research_service.batch_runner.BiqugeCatalogAdapter", Adapter)
    repository = _Repository()
    runner = _Runner(repository, outcomes)
    await runner.run(_request(2), "job-1")
    final = repository.updates[-1]
    assert final["status"] == status
    assert final["phase"] == status
    assert final["processed"] == processed
