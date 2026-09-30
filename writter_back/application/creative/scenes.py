"""自主模式场景功能契约；兼容旧书原有戏剧契约。"""

from typing import Any

FUNCTIONS = frozenset({"conflict", "setup", "aftermath", "relationship", "discovery"})


def validate_scene_identities(outline, total):
    """正文入口只允许已准入或本章明确准入的稳定人物ID。"""
    characters = [*total.get("main_characters", []), *outline.get("new_long_term_characters", [])]
    ids = {c["character_id"] for c in characters}
    for scene in outline.get("scenes") or []:
        chosen = scene.get("character_ids")
        if not isinstance(chosen, list) or not chosen or not set(chosen).issubset(ids):
            raise ValueError("场景出场人物必须引用已准入的character_id")
        if not isinstance(scene.get("allowed_information"), list) or not isinstance(scene.get("action_requirements"), list):
            raise ValueError("场景必须显式提供信息白名单与行动要求")


def validate_scene_contract(outline: dict[str, Any], chapter_number: int) -> list[str]:
    """安静章节按状态变化与后续作用验收，不补造冲突和反转。"""
    issues = []
    if outline.get("chapter_number") != chapter_number:
        issues.append("chapter_number 与当前章节不一致")
    intent = outline.get("chapter_intent") or {}
    if intent.get("primary_function") not in FUNCTIONS:
        issues.append("chapter_intent.primary_function 无效")
    if not intent.get("expected_effect") or not intent.get("subsequent_role"):
        issues.append("chapter_intent 缺少认知/关系/情绪效果或后续作用")
    scenes = outline.get("scenes") or []
    if not 1 <= len(scenes) <= 5:
        issues.append("自主模式 scenes 数量必须为1-5个")
    for index, scene in enumerate(scenes):
        issues.extend(_scene_issues(scene, index))
    for key in ("chapter_goal", "entry_state", "exit_state", "state_delta"):
        if not outline.get(key):
            issues.append(f"{key} 为空")
    return issues


def _scene_issues(scene: Any, index: int) -> list[str]:
    if not isinstance(scene, dict):
        return [f"scenes[{index}] 必须是对象"]
    errors = []
    function = scene.get("function")
    if function not in FUNCTIONS:
        errors.append(f"scenes[{index}].function 无效")
    if not scene.get("state_change") or not scene.get("purpose"):
        errors.append(f"scenes[{index}] 缺少状态变化或作用")
    if function == "conflict" and scene.get("active_opposition", True):
        if not scene.get("counteraction") or len(scene.get("tactics") or []) < 2:
            errors.append(f"scenes[{index}] 主动冲突缺少反制或策略变化")
        if not scene.get("cost"):
            errors.append(f"scenes[{index}] 冲突缺少代价")
    return errors
