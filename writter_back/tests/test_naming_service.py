"""Tests for deterministic classical-source naming infrastructure."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

from application.naming import (
    NamingValidationError,
    build_candidate_pool,
    hydrate_candidate,
    hydrate_candidates,
    load_source_entries,
    load_surnames,
    validate_name_selections,
)
from application.naming.sampling import rank_surnames, stable_seed


EXPECTED_WORKS = {"诗经", "楚辞", "古诗十九首", "乐府", "唐诗", "宋词"}
SOURCE_FIELDS = {
    "source_id",
    "work",
    "chapter",
    "quote",
    "token",
    "meaning",
    "pinyin",
    "gender_tendency",
    "genre_tags",
    "era_tags",
}


def _pool(novel_id: str, count: int = 24, **kwargs):
    return build_candidate_pool(
        tenant_id="tenant-a",
        novel_id=novel_id,
        proposal_version="proposal-1",
        prompt_version="2026-08-03.2",
        count=count,
        **kwargs,
    )


def test_source_data_is_complete_unique_and_balanced() -> None:
    entries = load_source_entries()
    assert len(entries) >= 120
    assert len({entry.source_id for entry in entries}) == len(entries)
    assert Counter(entry.work for entry in entries) == Counter(
        {work: 20 for work in EXPECTED_WORKS}
    )
    for entry in entries:
        values = entry.attribution()
        assert SOURCE_FIELDS == values.keys()
        assert all(values[field] for field in SOURCE_FIELDS)
        assert entry.gender_tendency in {"male", "female", "neutral"}


def test_surname_data_is_realistic_unique_and_positive() -> None:
    entries = load_surnames()
    assert 75 <= len(entries) <= 90
    assert len({entry.surname for entry in entries}) == len(entries)
    assert all(entry.surname.isalpha() and 1 <= len(entry.surname) <= 2 for entry in entries)
    assert all(entry.pinyin and 0 < entry.weight <= 1.2 for entry in entries)


def test_candidate_pool_is_stable_unique_and_covers_all_sources() -> None:
    first = _pool("novel-stable")
    second = _pool("novel-stable")
    assert first == second
    assert len({candidate.name for candidate in first}) == len(first)
    assert len({candidate.surname for candidate in first}) == len(first)
    assert {candidate.source.work for candidate in first} == EXPECTED_WORKS


def test_one_hundred_seeds_do_not_concentrate_a_surname() -> None:
    surnames = Counter(_pool(f"novel-{index}", 1)[0].surname for index in range(100))
    assert surnames.most_common(1)[0][1] <= 8


def test_recent_full_name_is_excluded_and_surname_is_downweighted() -> None:
    first = _pool("novel-recent", 1)[0]
    seed = stable_seed("tenant-a", "novel-recent", "proposal-1", "2026-08-03.2")
    surnames = load_surnames()
    baseline = rank_surnames(surnames, seed)
    penalized = rank_surnames(surnames, seed, {baseline[0].surname: 20})
    refreshed = _pool("novel-recent", 24, recent_names=[first.name])
    assert first.name not in {candidate.name for candidate in refreshed}
    assert penalized.index(baseline[0]) > 0


def test_hydration_uses_server_attribution_only() -> None:
    source = load_source_entries()[0]
    candidate = hydrate_candidate(
        {
            "surname": "赵",
            "source_id": source.source_id,
            "quote": "模型伪造的原句",
            "meaning": "模型伪造的解释",
        }
    )
    assert candidate.name == f"赵{source.token}"
    assert candidate.source.quote == source.quote
    assert candidate.source.meaning == source.meaning


def test_unknown_source_and_duplicate_candidates_are_rejected() -> None:
    with pytest.raises(NamingValidationError, match="未知 source_id"):
        hydrate_candidate({"surname": "赵", "source_id": "missing-source"})
    source_id = load_source_entries()[0].source_id
    payload = {"surname": "赵", "source_id": source_id}
    with pytest.raises(NamingValidationError, match="重复全名"):
        hydrate_candidates([payload, payload])


def test_selection_rejects_duplicate_and_recent_generated_name() -> None:
    source_id = load_source_entries()[0].source_id
    first = {"character_id": "lead-a", "surname": "赵", "source_id": source_id}
    second = {"character_id": "lead-b", "surname": "赵", "source_id": source_id}
    with pytest.raises(NamingValidationError) as duplicate_error:
        validate_name_selections([first, second])
    assert any("同书重复全名" in issue for issue in duplicate_error.value.issues)
    generated_name = hydrate_candidate(first).name
    with pytest.raises(NamingValidationError, match="近期作品已使用姓名"):
        validate_name_selections([first], recent_names=[generated_name])


def test_selection_allows_related_same_surname_and_user_name_override() -> None:
    sources = load_source_entries()
    payloads = [
        {"character_id": "parent", "surname": "赵", "source_id": sources[0].source_id},
        {"character_id": "child", "surname": "赵", "source_id": sources[1].source_id},
        {
            "character_id": "guest",
            "origin_type": "user_provided",
            "name": "欧阳自明",
            "surname": "欧阳",
        },
    ]
    selections = validate_name_selections(
        payloads,
        recent_names=["欧阳自明"],
        related_character_pairs=[("parent", "child")],
    )
    assert selections[-1].source is None
    assert selections[-1].origin_type == "user_provided"


def test_user_name_can_use_a_surname_outside_generated_corpus() -> None:
    selections = validate_name_selections([
        {"character_id": "guest", "origin_type": "user_provided", "name": "第五轻尘"}
    ])
    assert selections[0].name == "第五轻尘"
    assert selections[0].surname == "第五"
    assert selections[0].source is None


def test_new_naming_functions_stay_within_fifty_effective_lines() -> None:
    naming_root = Path(__file__).parents[1] / "application" / "naming"
    violations: list[str] = []
    for path in naming_root.glob("*.py"):
        source_lines = path.read_text(encoding="utf-8").splitlines()
        tree = ast.parse("\n".join(source_lines), filename=str(path))
        functions = (
            node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        for node in functions:
            body = source_lines[node.lineno - 1 : node.end_lineno]
            effective = [line for line in body if line.strip() and not line.lstrip().startswith("#")]
            if len(effective) > 50:
                violations.append(f"{path.name}:{node.name}={len(effective)}")
    assert not violations, violations
