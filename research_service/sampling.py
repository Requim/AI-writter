"""题材研究的确定性分层抽样。"""

from __future__ import annotations

from dataclasses import dataclass
from collections import defaultdict

from .contracts import CatalogCandidate


class SamplingShortageError(ValueError):
    """候选不足时禁止用重复作品伪造样本量。"""


@dataclass(frozen=True)
class SampleQuota:
    popular: int = 4
    new: int = 3
    recent: int = 3

    @classmethod
    def from_total(cls, total: int) -> "SampleQuota":
        """按 4:3:3 比例把调用方样本总数转换为分层配额。"""
        if total < 1:
            raise ValueError("抽样总数必须大于零")
        weights = (4, 3, 3)
        counts = [total * weight // sum(weights) for weight in weights]
        remainders = [total * weight % sum(weights) for weight in weights]
        order = sorted(range(3), key=lambda index: (-remainders[index], index))
        for index in order[: total - sum(counts)]:
            counts[index] += 1
        return cls(popular=counts[0], new=counts[1], recent=counts[2])

    @property
    def total(self) -> int:
        return self.popular + self.new + self.recent


def _ordered(candidates: list[CatalogCandidate]) -> list[CatalogCandidate]:
    return sorted(candidates, key=lambda item: (item.rank, item.title, item.url))


def _take_unique(
    candidates: list[CatalogCandidate], seen: set[str], count: int
) -> list[CatalogCandidate]:
    if count <= 0:
        return []
    result = []
    for candidate in _ordered(candidates):
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        result.append(candidate)
        if len(result) >= count:
            break
    return result


def select_stratified_candidates(
    candidates: list[CatalogCandidate],
    source_category: str,
    quota: SampleQuota = SampleQuota(),
    *,
    allow_shortage: bool = False,
    include_remaining: bool = False,
) -> tuple[CatalogCandidate, ...]:
    """按热门、新书、近期更新顺序选样，并用同类剩余候选补位。"""
    if quota.total < 1:
        raise ValueError("抽样配额必须大于零")
    grouped: dict[str, list[CatalogCandidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.source_category == source_category:
            grouped[candidate.bucket].append(candidate)
    selected: list[CatalogCandidate] = []
    seen: set[str] = set()
    for bucket, count in (("popular", quota.popular), ("new", quota.new), ("recent", quota.recent)):
        selected.extend(_take_unique(grouped[bucket], seen, count))
    remaining = [item for values in grouped.values() for item in values]
    selected.extend(_take_unique(remaining, seen, max(0, quota.total - len(selected))))
    if len(selected) < quota.total and (not allow_shortage or not selected):
        raise SamplingShortageError(
            f"{source_category} 候选不足：需要 {quota.total} 本，实际 {len(selected)} 本"
        )
    if include_remaining:
        selected.extend(_take_unique(remaining, seen, len(remaining)))
    return tuple(selected)
