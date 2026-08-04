"""Deterministic SHA-256 sampling helpers."""

from __future__ import annotations

from collections import Counter
from hashlib import sha256
from math import log
from typing import Iterable, Mapping, Sequence

from application.naming.models import SourceEntry, SurnameEntry

SURNAME_WEIGHT_CAP = 1.2


def stable_seed(
    tenant_id: object,
    novel_id: object,
    proposal_version: object,
    prompt_version: object,
) -> str:
    """按租户、作品、提案和提示词版本生成稳定 SHA-256 种子。"""
    parts = (tenant_id, novel_id, proposal_version, prompt_version)
    material = "\x1f".join(str(part).strip() for part in parts)
    if any(not str(part).strip() for part in parts):
        raise ValueError("稳定抽样种子的四个组成部分均不能为空")
    return sha256(material.encode("utf-8")).hexdigest()


def stable_digest(seed: str, namespace: str, value: str) -> bytes:
    """生成命名空间隔离的稳定摘要。"""
    material = f"{seed}\x1f{namespace}\x1f{value}"
    return sha256(material.encode("utf-8")).digest()


def _source_preference(
    entry: SourceEntry,
    gender_tendency: str | None,
    genre_tag: str | None,
    era_tag: str | None,
) -> int:
    penalty = 0
    if gender_tendency and entry.gender_tendency not in {gender_tendency, "neutral"}:
        penalty += 4
    if genre_tag and genre_tag not in entry.genre_tags:
        penalty += 2
    if era_tag and era_tag not in entry.era_tags:
        penalty += 1
    return penalty


def rank_sources(
    entries: Sequence[SourceEntry],
    seed: str,
    *,
    gender_tendency: str | None = None,
    genre_tag: str | None = None,
    era_tag: str | None = None,
) -> list[SourceEntry]:
    """稳定排序词条，并在候选池中轮转覆盖不同典籍来源。"""
    groups: dict[str, list[SourceEntry]] = {}
    for entry in entries:
        groups.setdefault(entry.work, []).append(entry)
    for work, group in groups.items():
        group.sort(key=lambda item: (
            _source_preference(item, gender_tendency, genre_tag, era_tag),
            stable_digest(seed, f"source:{work}", item.source_id),
        ))
    work_order = sorted(groups, key=lambda work: stable_digest(seed, "work", work))
    ranked: list[SourceEntry] = []
    for index in range(max(map(len, groups.values()), default=0)):
        ranked.extend(groups[work][index] for work in work_order if index < len(groups[work]))
    return ranked


def recent_surname_counts(
    recent_names: Iterable[str],
    known_surnames: Sequence[str],
) -> Counter[str]:
    """从近期全名中识别姓氏并统计频次。"""
    ordered = sorted(known_surnames, key=len, reverse=True)
    counts: Counter[str] = Counter()
    for raw_name in recent_names:
        name = str(raw_name).strip()
        surname = next((item for item in ordered if name.startswith(item)), "")
        if surname:
            counts[surname] += 1
    return counts


def _weighted_score(seed: str, entry: SurnameEntry, recent_count: int) -> float:
    digest = stable_digest(seed, "surname", entry.surname)
    uniform = (int.from_bytes(digest[:8], "big") + 1) / (2**64 + 1)
    capped_weight = min(entry.weight, SURNAME_WEIGHT_CAP)
    effective_weight = capped_weight / (1 + max(0, recent_count))
    return -log(uniform) / effective_weight


def rank_surnames(
    entries: Sequence[SurnameEntry],
    seed: str,
    recent_counts: Mapping[str, int] | None = None,
) -> list[SurnameEntry]:
    """按封顶权重稳定排序姓氏，并降低近期高频姓氏优先级。"""
    counts = recent_counts or {}
    return sorted(
        entries,
        key=lambda entry: (
            _weighted_score(seed, entry, int(counts.get(entry.surname, 0))),
            entry.surname,
        ),
    )
