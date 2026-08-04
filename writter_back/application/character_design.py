"""角色设计提案的服务端构建、兼容与选择解析。"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from application.naming import NameCandidate, NamingValidationError, validate_name_selections

PROFILE_FIELDS = (
    "identity", "external_goal", "internal_lack", "false_belief", "secret",
    "abilities", "limitations", "moral_red_line", "speech_fingerprint",
    "address_system", "arc_direction",
)
PROFILE_ALIASES = {
    "identity": ("identity", "身份"), "external_goal": ("external_goal", "外在目标", "目标"),
    "internal_lack": ("internal_lack", "内在缺口", "性格"),
    "false_belief": ("false_belief", "错误信念"), "secret": ("secret", "秘密"),
    "abilities": ("abilities", "能力"), "limitations": ("limitations", "限制"),
    "moral_red_line": ("moral_red_line", "道德红线"),
    "speech_fingerprint": ("speech_fingerprint", "语言指纹"),
    "address_system": ("address_system", "称谓体系"),
    "arc_direction": ("arc_direction", "人物弧方向"),
}


def _first_value(raw: Mapping[str, Any], aliases: Sequence[str]) -> str:
    return next((str(raw[key]).strip() for key in aliases if str(raw.get(key, "")).strip()), "")


def normalize_profile(value: Any, *, legacy: bool = False) -> dict[str, str]:
    """将新旧人物字段统一为英文 profile。"""
    raw = value if isinstance(value, Mapping) else {}
    nested = raw.get("profile") if isinstance(raw.get("profile"), Mapping) else {}
    merged = {**raw, **nested}
    profile = {field: _first_value(merged, PROFILE_ALIASES[field]) for field in PROFILE_FIELDS}
    if legacy:
        return {key: item or "旧总纲未提供" for key, item in profile.items()}
    return profile


def backfill_character_design(
    characters: Any, naming_policy: Any = None, relationships: Any = None,
) -> dict[str, Any] | None:
    """从旧总纲角色表构造无需再次调用模型的规范化角色设计。"""
    if not isinstance(characters, list) or not characters:
        return None
    normalized = [_legacy_character(item, index) for index, item in enumerate(characters)]
    normalized = [item for item in normalized if item]
    if not normalized:
        return None
    return {
        "naming_policy": naming_policy if isinstance(naming_policy, dict) else {},
        "characters": normalized,
        "relationships": relationships if isinstance(relationships, list) else [],
    }


def _legacy_character(value: Any, index: int) -> dict[str, Any] | None:
    raw = value if isinstance(value, Mapping) else {}
    name = _first_value(raw, ("name", "姓名"))
    if not name:
        return None
    return {
        "character_id": str(raw.get("character_id") or f"legacy-{index + 1}"),
        "role_type": str(raw.get("role_type") or raw.get("角色类型") or "supporting"),
        "name": name, "surname": str(raw.get("surname") or name[:1]),
        "origin_type": str(raw.get("origin_type") or "legacy_import"),
        "profile": normalize_profile(raw, legacy=True),
        **({"source_id": raw["source_id"], "source": raw.get("source", {})}
           if raw.get("source_id") else {}),
    }


def _candidate_payload(
    candidate: NameCandidate, profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = candidate.to_dict()
    source = payload["source"]
    profile = profile or {}
    identity = str(profile.get("identity") or "人物身份")
    arc = str(profile.get("arc_direction") or "人物弧方向")
    role_fit = f"典故意象“{source['meaning']}”与{identity}的{arc}相呼应"
    return {
        **payload, "given_name": source["token"], "source_title": source["work"],
        "source_chapter": source["chapter"], "source_quote": source["quote"],
        "meaning": source["meaning"], "pinyin": source["pinyin"],
        "role_fit": role_fit,
    }


def build_character_design_proposal(
    generated: Any,
    pool: Sequence[NameCandidate],
    *,
    proposal_version: int,
    prompt_version: str,
) -> dict[str, Any]:
    """校验模型引用并由服务端补齐全部姓名和典故字段。"""
    raw = generated if isinstance(generated, Mapping) else {}
    core_raw = raw.get("core_roles") if isinstance(raw.get("core_roles"), list) else []
    support_raw = raw.get("supporting_characters") if isinstance(raw.get("supporting_characters"), list) else []
    _validate_role_counts(core_raw, support_raw)
    index = {(item.surname, item.source.source_id): item for item in pool}
    used: set[tuple[str, str]] = set()
    core = [_build_core_role(item, index, used) for item in core_raw]
    support = [_build_support_role(item, index, used) for item in support_raw]
    _validate_character_ids([*core, *support])
    relationships = _normalize_relationships(raw.get("relationships"), {item["character_id"] for item in [*core, *support]})
    reserve = [_candidate_payload(item) for item in pool if (item.surname, item.source.source_id) not in used][:24]
    if len(reserve) != 24:
        raise NamingValidationError(["未使用姓名保留池不足 24 个"])
    return {
        "naming_policy": _naming_policy(pool, reserve, proposal_version, prompt_version),
        "core_roles": core, "supporting_characters": support, "relationships": relationships,
    }


def _validate_role_counts(core: list[Any], support: list[Any]) -> None:
    total = len(core) + len(support)
    issues = []
    if not 2 <= len(core) <= 4:
        issues.append("核心角色数量必须为 2-4")
    if not 6 <= total <= 10:
        issues.append("角色总数必须为 6-10")
    if issues:
        raise NamingValidationError(issues)


def _profile_or_error(raw: Mapping[str, Any], character_id: str) -> dict[str, str]:
    profile = normalize_profile(raw)
    missing = [field for field, value in profile.items() if not value]
    if missing:
        raise NamingValidationError([f"角色 {character_id} profile 缺少: {', '.join(missing)}"])
    return profile


def _reference(
    value: Any, index: Mapping[tuple[str, str], NameCandidate], used: set[tuple[str, str]],
) -> NameCandidate:
    raw = value if isinstance(value, Mapping) else {}
    key = (str(raw.get("surname", "")).strip(), str(raw.get("source_id", "")).strip())
    candidate = index.get(key)
    if candidate is None:
        raise NamingValidationError([f"模型引用不属于本次候选池: {key[0]}/{key[1]}"])
    if key in used:
        raise NamingValidationError([f"模型重复使用姓名引用: {candidate.name}"])
    used.add(key)
    return candidate


def _role_base(value: Any) -> tuple[Mapping[str, Any], str, str, dict[str, str]]:
    raw = value if isinstance(value, Mapping) else {}
    character_id = str(raw.get("character_id", "")).strip()
    role_type = str(raw.get("role_type", "")).strip()
    if not character_id or not role_type:
        raise NamingValidationError(["角色缺少 character_id 或 role_type"])
    return raw, character_id, role_type, _profile_or_error(raw, character_id)


def _build_core_role(
    value: Any, index: Mapping[tuple[str, str], NameCandidate], used: set[tuple[str, str]],
) -> dict[str, Any]:
    raw, character_id, role_type, profile = _role_base(value)
    refs = raw.get("name_candidates") if isinstance(raw.get("name_candidates"), list) else []
    if len(refs) != 3:
        raise NamingValidationError([f"核心角色 {character_id} 必须恰有 3 个姓名候选"])
    candidates = [_candidate_payload(_reference(item, index, used), profile) for item in refs]
    recommended = raw.get("recommended_candidate_index", 0)
    if not isinstance(recommended, int) or recommended not in range(3):
        raise NamingValidationError([f"核心角色 {character_id} 推荐候选索引无效"])
    return {
        "character_id": character_id, "role_type": role_type, "profile": profile,
        "name_candidates": candidates,
        "recommended_candidate_id": candidates[recommended]["candidate_id"],
    }


def _build_support_role(
    value: Any, index: Mapping[tuple[str, str], NameCandidate], used: set[tuple[str, str]],
) -> dict[str, Any]:
    raw, character_id, role_type, profile = _role_base(value)
    reference = raw.get("name_candidate")
    if reference is None and isinstance(raw.get("name_candidates"), list):
        reference = next(iter(raw["name_candidates"]), None)
    candidate = _candidate_payload(_reference(reference, index, used), profile)
    return {
        "character_id": character_id, "role_type": role_type, "profile": profile,
        "name": candidate["name"], "surname": candidate["surname"],
        "origin_type": "classical_source", **candidate,
    }


def _validate_character_ids(roles: list[dict[str, Any]]) -> None:
    ids = [item["character_id"] for item in roles]
    if len(ids) != len(set(ids)):
        raise NamingValidationError(["character_id 存在重复"])


def _normalize_relationships(value: Any, valid_ids: set[str]) -> list[dict[str, str]]:
    raw_items = value if isinstance(value, list) else []
    relationships: list[dict[str, str]] = []
    for value in raw_items:
        raw = value if isinstance(value, Mapping) else {}
        source = str(raw.get("source_character_id", "")).strip()
        target = str(raw.get("target_character_id", "")).strip()
        if source not in valid_ids or target not in valid_ids or source == target:
            raise NamingValidationError(["人物关系引用了未知或相同 character_id"])
        relationships.append({
            "source_character_id": source, "target_character_id": target,
            "relationship_type": str(raw.get("relationship_type", "")).strip(),
            "dynamic": str(raw.get("dynamic", "")).strip(),
        })
    return relationships


def _naming_policy(
    pool: Sequence[NameCandidate], reserve: list[dict[str, Any]], version: int, prompt_version: str,
) -> dict[str, Any]:
    works = sorted({item.source.work for item in pool})
    return {
        "origin": "verified_classical_corpus", "source_works": works,
        "recent_novel_window": 20, "proposal_version": version,
        "prompt_version": prompt_version, "reserve_pool": reserve,
        "rules": ["禁止同书重名", "核心非亲属不同姓", "禁止同尾字和近音"],
    }


def resolve_character_design(
    proposal: Mapping[str, Any], selection_value: Any, *, recent_names: Sequence[str] = (),
) -> dict[str, Any]:
    """仅从当前提案解析逐角色选择和自定义姓名。"""
    envelope = selection_value if isinstance(selection_value, Mapping) else {}
    choices = envelope.get("name_selections") if isinstance(envelope.get("name_selections"), Mapping) else {}
    custom = envelope.get("custom_names") if isinstance(envelope.get("custom_names"), Mapping) else {}
    core_roles = proposal.get("core_roles") if isinstance(proposal.get("core_roles"), list) else []
    raw_selections, chosen = _resolve_core_choices(core_roles, choices, custom)
    related_pairs = _family_pairs(proposal.get("relationships"))
    validated = validate_name_selections(
        raw_selections, recent_names=recent_names, related_character_pairs=related_pairs,
    )
    selected_map = {item.character_id: item for item in validated}
    core = [_accepted_core(role, selected_map[role["character_id"]], chosen) for role in core_roles]
    support = proposal.get("supporting_characters") if isinstance(proposal.get("supporting_characters"), list) else []
    characters = [*core, *[dict(item) for item in support]]
    _validate_final_names(characters, recent_names)
    return {
        "naming_policy": dict(proposal.get("naming_policy") or {}),
        "characters": characters, "relationships": list(proposal.get("relationships") or []),
    }


def _resolve_core_choices(
    roles: list[Any], choices: Mapping[str, Any], custom: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    payloads: list[dict[str, Any]] = []
    chosen: dict[str, dict[str, Any]] = {}
    for role in roles:
        character_id = str(role.get("character_id", ""))
        custom_name = str(custom.get(character_id, "")).strip()
        if custom_name:
            payloads.append({"character_id": character_id, "name": custom_name, "origin_type": "user_provided"})
            chosen[character_id] = {}
            continue
        candidate_id = str(choices.get(character_id) or role.get("recommended_candidate_id") or "")
        candidates = role.get("name_candidates") if isinstance(role.get("name_candidates"), list) else []
        candidate = next((item for item in candidates if item.get("candidate_id") == candidate_id), None)
        if candidate is None:
            raise NamingValidationError([f"角色 {character_id} 的姓名选择不属于当前提案"])
        payloads.append({"character_id": character_id, **candidate})
        chosen[character_id] = candidate
    return payloads, chosen


def _accepted_core(
    role: Mapping[str, Any], selection: Any, chosen: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    selected = selection.to_dict()
    candidate = chosen.get(str(role["character_id"]), {})
    return {
        "character_id": role["character_id"], "role_type": role["role_type"],
        "profile": dict(role["profile"]), **selected,
        **({"role_fit": candidate.get("role_fit", "")} if candidate else {}),
    }


def _family_pairs(value: Any) -> list[tuple[str, str]]:
    relationships = value if isinstance(value, list) else []
    markers = ("亲属", "家人", "父", "母", "兄", "弟", "姐", "妹", "夫妻", "family")
    return [
        (str(item.get("source_character_id", "")), str(item.get("target_character_id", "")))
        for item in relationships if isinstance(item, Mapping)
        and any(marker in str(item.get("relationship_type", "")).lower() for marker in markers)
    ]


def _validate_final_names(characters: list[dict[str, Any]], recent_names: Sequence[str]) -> None:
    names = [str(item.get("name", "")).strip() for item in characters]
    if not all(names) or len(names) != len(set(names)):
        raise NamingValidationError(["最终角色表存在空姓名或重复全名"])
    recent = set(recent_names)
    repeated = [item["name"] for item in characters if item.get("origin_type") != "user_provided" and item["name"] in recent]
    if repeated:
        raise NamingValidationError([f"近期作品已使用姓名: {', '.join(repeated)}"])
