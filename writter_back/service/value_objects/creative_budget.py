"""Versioned opt-in allocation; these guardrails are not quality guarantees."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ElasticBudgetPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1] = 1
    mode: Literal["elastic_v1"] = "elastic_v1"
    chapter_soft: int = Field(ge=1, le=48)
    chapter_hard: Literal[64] = 64
    future_chapter_reserve: int = Field(ge=1, le=24)
    review_round: Literal[12] = 12
    repair_round: Literal[20] = 20
    repair_minimum: Literal[18] = 18
    local_repair_round: Literal[15] = 15


class ChapterBudgetExtension(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    chapter: Literal[1]
    chapter_hard: Literal[72]
    control_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProgressRepairPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    version: Literal[1] = 1
    mode: Literal["progress_v1"]
    local_preferred: Literal[15] = 15
    local_minimum: Literal[9] = 9
    analysis_bucket: Literal["review"] = "review"
    postprocess_bucket: Literal["review"] = "review"


def model_spent(counters: dict) -> int:
    """Search/preparation_search describe a separate, overlapping allowance."""
    return sum(count for name, count in counters.items()
        if name in {"preparation", "review"} or name.startswith("chapter:"))


def canonical_bucket(limits: dict, bucket: str) -> str:
    root = bucket.split(":")[0]
    if root not in {"preparation", "chapter", "review", "search", "preparation_search"}:
        raise ValueError("未知预算池")
    if root == "chapter":
        suffix = bucket.removeprefix("chapter:")
        if not suffix.isdigit() or bucket != f"chapter:{int(suffix)}" or not 1 <= int(suffix) <= limits["chapters"]:
            raise ValueError("章节预算超出约定规模或使用了非规范编号")
    elif bucket != root:
        raise ValueError("不能通过预算池别名绕过上限")
    return root


def budget_capacity(limits: dict, counters: dict, bucket: str, *, include_round: bool = True) -> int:
    """One calculation for atomic reservations and read-only budget diagnostics."""
    root = canonical_bucket(limits, bucket)
    capacity = limits[root] - counters.get(bucket, 0)
    if root in {"search", "preparation_search"}:
        return max(0, min(capacity, limits["search"] - counters.get("search", 0)))
    remaining = limits.get("total", sum(limits[k] for k in ("preparation", "review"))) - model_spent(counters)
    policy = ElasticBudgetPolicy.model_validate(limits["policy"]) if "policy" in limits else None
    if policy and root == "chapter":
        chapter = int(bucket.split(":")[1])
        extension = ChapterBudgetExtension.model_validate(limits["chapter_extension"]) if "chapter_extension" in limits else None
        hard = extension.chapter_hard if extension and extension.chapter == chapter else policy.chapter_hard
        future = sum(max(0, policy.future_chapter_reserve - counters.get(f"chapter:{n}", 0))
            for n in range(chapter + 1, limits["chapters"] + 1))
        protected = future + sum(max(0, limits[k] - counters.get(k, 0)) for k in ("preparation", "review"))
        capacity = min(hard - counters.get(bucket, 0), remaining - protected)
    current = limits.get("round") or {}
    if include_round and current.get("status") == "active":
        if current["bucket"] == bucket:
            capacity = min(capacity, current["remaining"])
        else:
            remaining -= current["remaining"]
    return max(0, min(capacity, remaining))
