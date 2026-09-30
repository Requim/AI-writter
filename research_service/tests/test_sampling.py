from typing import Literal

import pytest

from research_service.contracts import CatalogCandidate
from research_service.sampling import SampleQuota, SamplingShortageError, select_stratified_candidates


def _candidate(
    number: int,
    bucket: Literal["popular", "new", "recent", "fallback"] = "popular",
) -> CatalogCandidate:
    return CatalogCandidate(
        url=f"https://www.biquge.pro/novel/{number}.html",
        title=f"样本{number}",
        source_category="科幻",
        bucket=bucket,
        rank=number,
    )


def test_sampling_fills_quota_from_unused_candidates_in_one_bucket() -> None:
    selected = select_stratified_candidates(
        [_candidate(number) for number in range(1, 15)], "科幻"
    )
    assert len(selected) == 10
    assert len({item.url for item in selected}) == 10


def test_sampling_respects_requested_total() -> None:
    quota = SampleQuota.from_total(3)
    candidates = [_candidate(1, "popular"), _candidate(2, "new"), _candidate(3, "recent")]
    selected = select_stratified_candidates(candidates, "科幻", quota)
    assert len(selected) == 3
    assert quota == SampleQuota(popular=1, new=1, recent=1)


def test_sampling_rejects_real_shortage() -> None:
    with pytest.raises(SamplingShortageError, match="实际 2 本"):
        select_stratified_candidates([_candidate(1), _candidate(2)], "科幻")
