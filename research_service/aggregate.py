"""将样本增量汇总为按项目题材组织的知识包。"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Iterable, Literal
from uuid import uuid4

from .contracts import (
    GenreKnowledgePackage, PatternCluster, ResearchSample,
    OPENING_PATTERN_LABELS, PROJECT_GENRE_LABELS,
)
from .taxonomy import normalize_term


def _top(counter: Counter[str], limit: int = 8) -> tuple[str, ...]:
    return tuple(key for key, _ in counter.most_common(limit))


def _representative_notes(members: list[ResearchSample]) -> tuple[str, ...]:
    notes = []
    for member in members:
        card = member.card
        observations = [card.reader_promise, card.plot_engine,
                        *card.opening_beats, *card.originality_directions]
        text = "；".join(dict.fromkeys(item for item in observations if item))
        if text:
            notes.append(f"{member.sample_id}: {text[:800]}")
    return tuple(notes[:8])


def _clusters(samples: list[ResearchSample]) -> tuple[PatternCluster, ...]:
    dimension_type = Literal["opening_pattern", "highlight_mechanism"]
    grouped: dict[tuple[dimension_type, str], list[ResearchSample]] = defaultdict(list)
    for sample in samples:
        grouped[("opening_pattern", sample.card.opening_pattern)].append(sample)
        for mechanism in sample.card.highlight_mechanisms:
            grouped[("highlight_mechanism", normalize_term(mechanism))].append(sample)
    result = []
    for (dimension, key), members in sorted(grouped.items()):
        result.append(PatternCluster(
            dimension=dimension,
            key=key,
            sample_count=len(members),
            sample_ids=tuple(member.sample_id for member in members)[:200],
            representative_notes=_representative_notes(members),
        ))
    return tuple(result)


def _guidance(openings: Counter[str], mechanisms: Counter[str]) -> tuple[str, ...]:
    guidance = []
    if openings:
        labels = [OPENING_PATTERN_LABELS.get(key, key) for key in _top(openings, 4)]
        guidance.append(f"当前样本中出现较多的开局分支：{'、'.join(labels)}。")
    if mechanisms:
        guidance.append(f"当前样本中出现较多的看点机制：{'、'.join(_top(mechanisms, 6))}。")
    guidance.append("以上是样本分布观察，不直接证明市场因果或作品质量。")
    return tuple(guidance)


def build_knowledge_package(
    project_genre: str,
    samples: Iterable[ResearchSample],
    version: int,
    knowledge_version_id: str | None = None,
    status: Literal["draft", "review", "approved", "rejected"] = "draft",
) -> GenreKnowledgePackage:
    """从样本重建类型知识包，保证可重复和可回滚。"""
    members = list({sample.sample_id: sample for sample in samples
                    if sample.primary_project_genre == project_genre
                    or project_genre in sample.secondary_project_genres}.values())
    openings = Counter(sample.card.opening_pattern for sample in members)
    mechanisms = Counter(
        normalize_term(item)
        for sample in members
        for item in sample.card.highlight_mechanisms
    )
    sources = tuple(sorted({sample.card.metadata.source_category for sample in members}))
    evidence = tuple(sample.sample_id for sample in members)
    package_id = knowledge_version_id or f"knowledge-{project_genre}-{uuid4().hex}"
    retrieval_text = "\n".join([
        project_genre,
        PROJECT_GENRE_LABELS.get(project_genre, project_genre),
        " ".join(sources),
        " ".join(_guidance(openings, mechanisms)),
        " ".join(_top(openings)),
        " ".join(_top(mechanisms)),
        " ".join(
            sample.card.reader_promise
            for sample in members
            if sample.card.reader_promise
        )[:4000],
    ])
    return GenreKnowledgePackage(
        knowledge_version_id=package_id,
        project_genre=project_genre,
        version=version,
        status=status,
        sample_count=len(members),
        source_categories=sources,
        opening_pattern_counts=dict(openings),
        mechanism_counts=dict(mechanisms),
        clusters=_clusters(members),
        writing_guidance=_guidance(openings, mechanisms),
        originality_rules=("只提炼机制和结构，不复述连续原文、专名或独特设定组合。",),
        limitations=tuple(dict.fromkeys([
            "样本不足或来源偏斜时，类型报告只代表当前采样范围。",
            *[note for sample in members for note in sample.card.limitations],
            *["包含低置信度样本；未观察到的正文机制不得视为已验证。"
              for sample in members if sample.card.confidence == "low"],
        ])),
        evidence_sample_ids=evidence,
        retrieval_text=retrieval_text,
        created_at=datetime.now(timezone.utc),
    )
