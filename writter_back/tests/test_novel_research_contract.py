import pytest

from infrastructure.research.sampling import SampleQuota, SamplingShortageError, select_stratified_candidates
from service.value_objects.novel_research import (
    CatalogCandidate,
    ChapterIndex,
    NovelMetadata,
    NovelPatternCard,
    OpeningMetrics,
    ResearchBatch,
    SourceLocation,
    build_genre_pattern_report,
    project_genres_for,
)


def _candidate(number: int, bucket: str) -> CatalogCandidate:
    return CatalogCandidate(
        url=f"https://www.biquge.pro/novel/{number}.html",
        title=f"样本{number}", source_category="科幻", bucket=bucket, rank=number,
    )


def _card(number: int, pattern: str) -> NovelPatternCard:
    metadata = NovelMetadata(
        source_url=f"https://www.biquge.pro/novel/{number}.html",
        source_id=str(number), title=f"样本{number}", source_category="科幻",
    )
    index = ChapterIndex(titles=("第1章",), total_count=1, digest="a" * 64)
    evidence = (SourceLocation(url=metadata.source_url, paraphrase="首章先出现异常，再迫使主角选择。"),)
    return NovelPatternCard(
        metadata=metadata, chapter_index=index, opening_metrics=OpeningMetrics(
            character_count=100, paragraph_count=4, dialogue_ratio=0.1,
        ), highlight_mechanisms=("规则压力",), opening_pattern=pattern,
        opening_beats=("状态", "异常", "选择", "承诺"), evidence=evidence,
        confidence="medium",
    )


def test_sampling_uses_strata_and_deduplicates() -> None:
    candidates = [_candidate(number, "popular") for number in range(1, 6)]
    candidates += [_candidate(number, "new") for number in range(6, 10)]
    candidates += [_candidate(number, "recent") for number in range(10, 14)]
    selected = select_stratified_candidates(candidates, "科幻")
    assert len(selected) == 10
    assert {item.bucket for item in selected} == {"popular", "new", "recent"}
    assert len({item.url for item in selected}) == 10


def test_sampling_rejects_shortage_instead_of_repeating() -> None:
    candidates = [_candidate(1, "popular"), _candidate(2, "new")]
    with pytest.raises(SamplingShortageError):
        select_stratified_candidates(candidates, "科幻", SampleQuota(1, 1, 1))


def test_sampling_fills_quota_from_unused_candidates_in_one_bucket() -> None:
    candidates = [_candidate(number, "popular") for number in range(1, 15)]
    selected = select_stratified_candidates(candidates, "科幻")
    assert len(selected) == 10
    assert len({item.url for item in selected}) == 10


@pytest.mark.parametrize(
    ("total", "expected"),
    [(1, (1, 0, 0)), (2, (1, 1, 0)), (3, (1, 1, 1)), (10, (4, 3, 3))],
)
def test_sample_quota_scales_to_requested_total(total: int, expected: tuple[int, int, int]) -> None:
    quota = SampleQuota.from_total(total)
    assert (quota.popular, quota.new, quota.recent) == expected


def test_project_mapping_keeps_game_category_unforced() -> None:
    assert project_genres_for("科幻") == ("sci_fi",)
    assert project_genres_for("游戏") == ()


def test_report_aggregates_only_structured_cards() -> None:
    cards = [_card(1, "mystery_question"), _card(2, "mystery_question"), _card(3, "world_reveal")]
    report = build_genre_pattern_report(cards, "科幻")
    assert report.sample_count == 3
    assert report.opening_pattern_counts["mystery_question"] == 2
    assert "规则压力" in report.common_mechanisms
    assert "text" not in report.model_dump()


def test_report_rejects_mixed_categories() -> None:
    cards = [_card(1, "mystery_question"), _card(2, "world_reveal")]
    changed = cards[1].model_copy(update={"metadata": cards[1].metadata.model_copy(update={"source_category": "玄幻"})})
    with pytest.raises(ValueError, match="同一来源分类"):
        build_genre_pattern_report([cards[0], changed], "科幻")


def test_batch_contract_keeps_version_and_digest() -> None:
    batch = ResearchBatch(
        batch_id="batch-20260920",
        fetched_at="2026-09-20T10:00:00+08:00",
        categories=("科幻",), parser_version="parser-v1", policy_version="policy-v1",
        digest="b" * 64,
    )
    assert batch.status == "draft"
    assert batch.source_host == "biquge.pro"


def test_value_objects_reject_external_sources() -> None:
    with pytest.raises(ValueError, match="biquge.pro"):
        SourceLocation(url="https://example.com/novel/1.html", paraphrase="外部来源")
    with pytest.raises(ValueError, match="biquge.pro"):
        NovelMetadata(source_url="https://example.com/novel/1.html", source_id="1", title="样本", source_category="科幻")
