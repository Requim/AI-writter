"""Public candidate construction and selection-validation API."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable, Mapping, Sequence

from application.naming.models import (
    NameCandidate,
    NameSelection,
    NamingValidationError,
    SourceEntry,
    SurnameEntry,
)
from application.naming.resources import load_source_entries, load_surnames
from application.naming.sampling import (
    rank_sources,
    rank_surnames,
    recent_surname_counts,
    stable_seed,
)

_CUSTOM_COMPOUND_SURNAMES = (
    "欧阳", "司马", "上官", "诸葛", "东方", "皇甫", "尉迟", "公孙",
    "慕容", "司徒", "司空", "令狐", "宇文", "长孙", "南宫", "第五",
)


def _candidate_id(seed: str, surname: str, source_id: str) -> str:
    material = f"{seed}\x1f{surname}\x1f{source_id}"
    return sha256(material.encode("utf-8")).hexdigest()[:20]


def _source_index() -> dict[str, SourceEntry]:
    return {entry.source_id: entry for entry in load_source_entries()}


def _known_surname(name: str) -> str:
    surnames = sorted((entry.surname for entry in load_surnames()), key=len, reverse=True)
    matched = next((surname for surname in surnames if name.startswith(surname)), "")
    compound = next((item for item in _CUSTOM_COMPOUND_SURNAMES if name.startswith(item)), "")
    return matched or compound or name[:1]


def hydrate_candidate(
    payload: Mapping[str, Any],
    *,
    seed: str = "model-response",
) -> NameCandidate:
    """只接受姓氏和 source_id，并由服务端词库补齐姓名与出处。"""
    surname = str(payload.get("surname", "")).strip()
    source_id = str(payload.get("source_id", "")).strip()
    known_surnames = {entry.surname for entry in load_surnames()}
    source = _source_index().get(source_id)
    issues: list[str] = []
    if surname not in known_surnames:
        issues.append(f"未知或缺失姓氏: {surname or '<empty>'}")
    if source is None:
        issues.append(f"未知 source_id: {source_id or '<empty>'}")
    if issues or source is None:
        raise NamingValidationError(issues)
    name = f"{surname}{source.token}"
    return NameCandidate(_candidate_id(seed, surname, source_id), name, surname, source)


def hydrate_candidates(
    payloads: Iterable[Mapping[str, Any]],
    *,
    seed: str = "model-response",
) -> tuple[NameCandidate, ...]:
    """批量回填候选并拒绝同一批次中的重复全名。"""
    candidates = tuple(hydrate_candidate(item, seed=seed) for item in payloads)
    names = [item.name for item in candidates]
    if len(names) != len(set(names)):
        raise NamingValidationError(["候选姓名存在重复全名"])
    return candidates


def build_candidate_pool(
    *,
    tenant_id: object,
    novel_id: object,
    proposal_version: object,
    prompt_version: object,
    count: int,
    recent_names: Iterable[str] = (),
    excluded_names: Iterable[str] = (),
    gender_tendency: str | None = None,
    genre_tag: str | None = None,
    era_tag: str | None = None,
) -> tuple[NameCandidate, ...]:
    """构建可复现、跨来源且排除近期重名的姓名候选池。"""
    sources = load_source_entries()
    surnames = load_surnames()
    if count <= 0 or count > min(len(sources), len(surnames)):
        raise ValueError("候选数量必须在 1 到词库可用上限之间")
    seed = stable_seed(tenant_id, novel_id, proposal_version, prompt_version)
    source_order = rank_sources(
        sources,
        seed,
        gender_tendency=gender_tendency,
        genre_tag=genre_tag,
        era_tag=era_tag,
    )
    recent = tuple(str(name).strip() for name in recent_names if str(name).strip())
    known = tuple(entry.surname for entry in surnames)
    surname_order = rank_surnames(surnames, seed, recent_surname_counts(recent, known))
    blocked = set(recent) | {str(name).strip() for name in excluded_names}
    candidates = _pair_candidates(seed, surname_order, source_order, blocked, count)
    if len(candidates) != count:
        raise NamingValidationError(["排除近期姓名后，可用候选数量不足"])
    return tuple(candidates)


def _pair_candidates(
    seed: str,
    surnames: Sequence[SurnameEntry],
    sources: Sequence[SourceEntry],
    blocked: set[str],
    count: int,
) -> list[NameCandidate]:
    candidates: list[NameCandidate] = []
    used_sources: set[str] = set()
    for surname in surnames:
        source = next(
            (item for item in sources if item.source_id not in used_sources and f"{surname.surname}{item.token}" not in blocked),
            None,
        )
        if source is None:
            continue
        used_sources.add(source.source_id)
        candidate = hydrate_candidate(
            {"surname": surname.surname, "source_id": source.source_id},
            seed=seed,
        )
        candidates.append(candidate)
        if len(candidates) == count:
            break
    return candidates


def _selection_from_payload(payload: Mapping[str, Any]) -> NameSelection:
    character_id = str(payload.get("character_id", "")).strip()
    origin_type = str(payload.get("origin_type", "classical_source")).strip()
    if not character_id:
        raise NamingValidationError(["character_id 不能为空"])
    if origin_type not in {"classical_source", "user_provided"}:
        raise NamingValidationError([f"未知 origin_type: {origin_type}"])
    if origin_type == "user_provided":
        name = str(payload.get("name", "")).strip()
        supplied_surname = str(payload.get("surname", "")).strip()
        surname = supplied_surname or _known_surname(name) or name[:1]
        if len(name) < 2 or not surname or not name.startswith(surname):
            raise NamingValidationError([f"自定义姓名或姓氏无效: {name}"])
        return NameSelection(character_id, name, surname, origin_type)
    candidate = hydrate_candidate(payload)
    supplied_name = str(payload.get("name", candidate.name)).strip()
    if supplied_name != candidate.name:
        raise NamingValidationError([f"姓名与 source_id 不匹配: {supplied_name}"])
    return NameSelection(character_id, candidate.name, candidate.surname, origin_type, candidate.source)


def validate_name_selections(
    payloads: Iterable[Mapping[str, Any]],
    *,
    recent_names: Iterable[str] = (),
    related_character_pairs: Iterable[tuple[str, str]] = (),
) -> tuple[NameSelection, ...]:
    """校验最终方案的重名、同姓、同尾字、近音和来源一致性。"""
    selections = tuple(_selection_from_payload(item) for item in payloads)
    issues = _selection_issues(selections, recent_names, related_character_pairs)
    if issues:
        raise NamingValidationError(issues)
    return selections


def _selection_issues(
    selections: Sequence[NameSelection],
    recent_names: Iterable[str],
    related_pairs: Iterable[tuple[str, str]],
) -> list[str]:
    issues: list[str] = []
    generated_recent = set(str(name).strip() for name in recent_names)
    related = {frozenset(pair) for pair in related_pairs}
    character_ids = [item.character_id for item in selections]
    if len(character_ids) != len(set(character_ids)):
        issues.append("character_id 存在重复")
    for index, current in enumerate(selections):
        if current.origin_type != "user_provided" and current.name in generated_recent:
            issues.append(f"近期作品已使用姓名: {current.name}")
        for other in selections[:index]:
            pair = frozenset((current.character_id, other.character_id))
            if current.name == other.name:
                issues.append(f"同书重复全名: {current.name}")
            if current.surname == other.surname and pair not in related:
                issues.append(f"非亲属核心角色同姓: {current.surname}")
            if current.name[-1:] == other.name[-1:]:
                issues.append(f"核心角色同尾字: {current.name[-1:]}")
            current_pinyin = _selection_pinyin(current)
            other_pinyin = _selection_pinyin(other)
            if current_pinyin and current_pinyin == other_pinyin:
                issues.append(f"核心角色名字近音: {current.name}/{other.name}")
    return issues


def _selection_pinyin(selection: NameSelection) -> str:
    if selection.source is None:
        return ""
    return "".join(selection.source.pinyin.lower().split())
