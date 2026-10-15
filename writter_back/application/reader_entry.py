"""Compile confirmed opening information into scene-sized writing assignments."""

from __future__ import annotations

import json
from copy import deepcopy

from application.prompts.template_loader import render_prompt


def entry_rules(chapter_number: int) -> str:
    return render_prompt("chapter/reader_entry_v1.txt", include_active_rules=False,
                         chapter_number=chapter_number)


def validate_reader_entry(outline: dict, chapter_number: int) -> dict:
    entry = outline.get("reader_entry")
    if not isinstance(entry, dict) or not str(entry.get("everyday_problem") or "").strip():
        raise RuntimeError("读者入场缺少可理解的眼前问题")
    rows = entry.get("required_information")
    deferred = entry.get("deferred_information")
    if not isinstance(rows, list) or not rows or not isinstance(deferred, list):
        raise RuntimeError("读者入场需区分必要信息和暂缓披露信息")
    scenes = outline.get("scenes") or []
    purposes = set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("purpose") not in {
            "who", "relationship", "goal", "obstacle", "hook"}
                or not isinstance(row.get("fact"), str) or not row["fact"].strip()
                or type(row.get("scene_index")) is not int or row["scene_index"] != 1):
            raise RuntimeError("读者入场必要信息必须对应第一场景，并使用有效purpose与fact")
        purposes.add(row["purpose"])
        fact = row["fact"].strip()
        allowed = scenes[0].get("allowed_information") or [] if scenes else []
        if not any(isinstance(value, str) and fact in value for value in allowed):
            raise RuntimeError("读者入场必要信息未进入第一场景allowed_information：" + fact)
        if any(isinstance(value, str) and (fact in value or value in fact) for value in deferred if value):
            raise RuntimeError("读者入场同一事实不能既要求交代又禁止披露：" + fact)
    required = {"who", "goal", "obstacle", "hook"} if chapter_number == 1 else {"goal", "obstacle", "hook"}
    if not required.issubset(purposes):
        raise RuntimeError("读者入场缺少必要理解目标：" + "、".join(sorted(required - purposes)))
    if any(not isinstance(value, str) or not value.strip() for value in deferred):
        raise RuntimeError("读者入场暂缓披露信息必须为非空文本")
    return deepcopy(entry)


def public_reader_entry(entry: dict | None) -> dict:
    """The writer sees authorized entry facts, never the actual deferred answers."""
    entry = entry if isinstance(entry, dict) else {}
    return {key: deepcopy(entry[key]) for key in (
        "everyday_problem", "required_information", "must_understand") if key in entry}


def deferred_reader_information(material: object) -> set[str]:
    result: set[str] = set()
    if isinstance(material, dict):
        entry = material.get("reader_entry")
        if isinstance(entry, dict):
            result.update(value for value in entry.get("deferred_information", [])
                          if isinstance(value, str) and value.strip())
        for value in material.values():
            result.update(deferred_reader_information(value))
    elif isinstance(material, list):
        for value in material:
            result.update(deferred_reader_information(value))
    return result


def prose_reader_material(material: dict, *, enabled: bool, deferred: set[str] | None = None) -> dict:
    """Apply the same entry-information boundary in assisted and autonomous prose."""
    if not enabled:
        return material
    blocked = deferred_reader_information(material) if deferred is None else deferred

    def project(value):
        if isinstance(value, dict):
            return {key: project(public_reader_entry(item)) if key == "reader_entry" else project(item)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [project(item) for item in value]
        if isinstance(value, str):
            for secret in sorted(blocked, key=len, reverse=True):
                value = value.replace(secret, "[暂缓披露的信息]")
        return deepcopy(value)

    return project(material)


def prose_reader_context(outline: dict, total: dict, *, enabled: bool,
                         chapter_number: int = 1) -> tuple[dict, dict]:
    authorized = [fact for scene in outline.get("scenes", [])
                  for fact in scene.get("allowed_information", []) if isinstance(fact, str)]
    own = deferred_reader_information(outline) if enabled else set()
    macro = deferred_reader_information(total) if enabled else set()
    # Later explicit authorization releases brief deferrals, never current chapter prohibitions.
    if chapter_number > 1:
        macro = {secret for secret in macro if not any(secret in fact for fact in authorized)}
    deferred = own | macro
    if deferred:
        from application.errors import RetryableWorkflowError
        if any(secret in fact for secret in deferred for fact in authorized):
            raise RetryableWorkflowError("读者入场信息边界冲突：当前授权事实同时要求暂缓披露，请交回审阅")
    return (prose_reader_material(outline, enabled=enabled, deferred=deferred),
            prose_reader_material(total, enabled=enabled, deferred=deferred))


def _text(value: object) -> str:
    if isinstance(value, dict):
        return "；".join(f"{key}：{_text(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "；".join(_text(item) for item in value)
    return str(value or "未提供")


def writing_assignment(outline: dict, scene: dict | None = None) -> str:
    scenes = [scene] if scene is not None else outline.get("scenes") or []
    facts = [value for item in scenes for value in item.get("allowed_information") or []]
    actions = [value for item in scenes for value in item.get("action_requirements") or []]
    intent = outline.get("chapter_intent") or {}
    scene_goal = scene.get("scene_goal") or scene.get("purpose") if scene else outline.get("chapter_goal")
    contract = outline.get("reader_contract") or {}
    ending = (scene.get("state_change") or scene.get("state_delta")) if scene else outline.get("state_delta")
    return render_prompt("chapter/writing_assignment_v1.txt", include_active_rules=False,
        chapter_goal=_text(outline.get("chapter_goal")), scene_goal=_text(scene_goal),
        motive=_text(outline.get("desire") or contract.get("immediate_goal") or intent.get("expected_effect")),
        opposition=_text(scene.get("counteraction") or scene.get("obstacle")) if scene else _text(outline.get("obstacle")),
        facts=_text(facts), actions=_text(actions), change=_text(ending),
        entry_state=_text(outline.get("entry_state")), ending=_text(outline.get("ending_mode")),
        information_boundary=_text(outline.get("knowledge_boundaries") or "仅使用当前场景授权信息，不展开隐藏真相"),
        execution=json.dumps(outline.get("chapter_execution_contract") or {}, ensure_ascii=False))
