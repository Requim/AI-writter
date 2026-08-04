"""Continuity context helpers shared by planning, writing and review nodes."""

from __future__ import annotations

import json
import re
from typing import Any


_SECTION_PATTERN = re.compile(r"<([^>]+)>\s*")
_SECTION_ORDER = (
    "S层故事状态",
    "P层滚动规划",
    "M层近期章节",
    "L层历史章节摘录",
)
_SECTION_WEIGHTS = {
    "S层故事状态": 0.34,
    "P层滚动规划": 0.20,
    "M层近期章节": 0.31,
    "L层历史章节摘录": 0.15,
}
_CHARACTER_NAME_KEYS = ("name", "姓名", "character_name", "角色名")
_CHARACTER_ROLE_KEYS = (
    "role_type",
    "role",
    "identity",
    "身份",
    "角色定位",
    "定位",
)


def compact_text(text: str, budget: int, *, tail_ratio: float = 0.35) -> str:
    """Keep both the beginning and ending when text exceeds a character budget."""
    clean = str(text or "").strip()
    if budget <= 0 or not clean:
        return ""
    if len(clean) <= budget:
        return clean
    marker = "\n...（中间内容按预算压缩）...\n"
    available = max(0, budget - len(marker))
    tail_size = int(available * tail_ratio)
    head_size = available - tail_size
    return f"{clean[:head_size]}{marker}{clean[-tail_size:]}"


def split_memory_sections(memory_context: str) -> dict[str, str]:
    """Parse the formatted hierarchical memory into named sections."""
    context = str(memory_context or "").strip()
    if not context:
        return {}
    matches = list(_SECTION_PATTERN.finditer(context))
    if not matches:
        return {"M层近期章节": context}
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(context)
        sections[match.group(1)] = context[start:end].strip()
    return sections


def build_budgeted_context(memory_context: str, max_chars: int = 3200) -> str:
    """Build a section-aware context without dropping all trailing memory layers."""
    sections = split_memory_sections(memory_context)
    present = [name for name in _SECTION_ORDER if sections.get(name)]
    if not present:
        return "无"

    weights = {name: _SECTION_WEIGHTS[name] for name in present}
    total_weight = sum(weights.values())
    parts: list[str] = []
    for name in present:
        budget = max(180, int(max_chars * weights[name] / total_weight))
        parts.append(f"<{name}>\n{compact_text(sections[name], budget)}")
    return "\n\n".join(parts)


def extract_story_state(memory_context: str) -> str:
    """Return the latest structured S-layer state, if one exists."""
    return split_memory_sections(memory_context).get("S层故事状态", "")


def _character_value(character: dict[str, Any], keys: tuple[str, ...]) -> str:
    profile = character.get("profile")
    sources = (character, profile) if isinstance(profile, dict) else (character,)
    for source in sources:
        for key in keys:
            value = str(source.get(key) or "").strip()
            if value:
                return value
    return ""


def _main_characters(total_outline: dict[str, Any]) -> list[dict[str, Any]]:
    characters = total_outline.get("main_characters", [])
    if not isinstance(characters, list):
        return []
    return [item for item in characters if isinstance(item, dict)]


def related_character_cards(
    total_outline: dict[str, Any], related_context: Any
) -> list[dict[str, Any]]:
    """返回在当前场景、细纲或正文中被提及的完整角色卡。"""
    characters = _main_characters(total_outline)
    if not related_context:
        return []
    context_text = json.dumps(related_context, ensure_ascii=False, default=str)
    return [
        character
        for character in characters
        if (name := _character_value(character, _CHARACTER_NAME_KEYS))
        and name in context_text
    ]


def _global_story_rules(total_outline: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_title": total_outline.get("source_title", ""),
        "source_summary": total_outline.get("source_summary", ""),
        "creative_brief": total_outline.get("creative_brief", {}),
        "world_rules": total_outline.get("story_background", ""),
        "main_plot": total_outline.get("main_plot", {}),
        "writing_style": total_outline.get("writing_style", ""),
        "prompt_version": total_outline.get("prompt_version", ""),
    }


def _character_index(
    characters: list[dict[str, Any]], active_ids: set[int]
) -> str:
    lines = []
    for character in characters:
        if id(character) in active_ids:
            continue
        name = _character_value(character, _CHARACTER_NAME_KEYS) or "未命名角色"
        role = _character_value(character, _CHARACTER_ROLE_KEYS) or "未标注身份"
        lines.append(f"- {name} | {role}")
    return "\n".join(lines) or "无"


def build_story_bible(
    total_outline: dict[str, Any],
    max_chars: int = 3200,
    *,
    related_context: Any = None,
) -> str:
    """按全局规则、相关角色完整卡和其他角色索引构建正史上下文。"""
    characters = _main_characters(total_outline)
    active = related_character_cards(total_outline, related_context)
    active_text = json.dumps(active, ensure_ascii=False, indent=2) if active else "无"
    index_text = _character_index(characters, {id(item) for item in active})
    fixed_size = len(active_text) + len(index_text) + 80
    global_budget = max(400, max_chars - fixed_size)
    global_text = compact_text(
        json.dumps(_global_story_rules(total_outline), ensure_ascii=False, indent=2),
        global_budget,
        tail_ratio=0.25,
    )
    return (
        f"<全局规则>\n{global_text}\n\n"
        f"<当前场景角色卡>\n{active_text}\n\n"
        f"<其他角色索引>\n{index_text}"
    )


def compact_story_bible(story_bible: str, budget: int) -> str:
    """仅压缩全局规则，保证角色卡和角色索引不会从中间被截断。"""
    clean = str(story_bible or "").strip()
    if not clean or len(clean) <= budget:
        return clean
    sections = split_memory_sections(clean)
    active = sections.get("当前场景角色卡")
    index = sections.get("其他角色索引")
    if active is None or index is None:
        return compact_text(clean, budget, tail_ratio=0.25)
    fixed = f"<当前场景角色卡>\n{active}\n\n<其他角色索引>\n{index}"
    global_budget = max(0, budget - len(fixed) - len("<全局规则>\n\n\n"))
    global_rules = compact_text(sections.get("全局规则", ""), global_budget)
    return f"<全局规则>\n{global_rules or '无'}\n\n{fixed}"


def rolling_plan_covers(plan: Any, chapter_number: int) -> bool:
    """Return whether a rolling plan contains a beat for the requested chapter."""
    if not isinstance(plan, list):
        return False
    for beat in plan:
        if not isinstance(beat, dict):
            continue
        try:
            if int(beat.get("chapter_number", -1)) == chapter_number:
                return True
        except (TypeError, ValueError):
            continue
    return False


def normalize_chapter_contract(
    outline: dict[str, Any], chapter_number: int
) -> dict[str, Any]:
    """Fill compatibility defaults while preserving user/model supplied fields."""
    normalized = dict(outline)
    normalized["chapter_number"] = chapter_number
    normalized.setdefault("chapter_goal", "推进当前卷核心冲突")
    normalized.setdefault("pov_character", "")
    normalized.setdefault("dramatic_question", "本章冲突将如何改变当前局势")
    normalized.setdefault("desire", "推进当前目标")
    normalized.setdefault("obstacle", "对手或局势主动阻止目标达成")
    normalized.setdefault("tactics", ["延续既定行动", "受阻后调整策略"])
    normalized.setdefault("turn", "行动导致局势发生变化")
    normalized.setdefault("price_paid", "目标推进伴随真实代价")
    normalized.setdefault("state_delta", "人物、关系、信息或资源状态发生变化")
    normalized.setdefault("ending_mode", "decision")
    normalized.setdefault("key_events", [])
    normalized.setdefault("entry_state", {})
    normalized.setdefault("exit_state", {})
    normalized.setdefault("causal_chain", [])
    normalized.setdefault("state_changes", [])
    normalized.setdefault("knowledge_boundaries", [])
    normalized.setdefault("continuity_constraints", [])
    normalized.setdefault("logic_hooks", {"callback": "无", "setup": "无"})
    normalized.setdefault("rolling_plan", [])
    normalized.setdefault("scenes", [])
    for field in (
        "key_events",
        "tactics",
        "causal_chain",
        "state_changes",
        "knowledge_boundaries",
        "continuity_constraints",
        "rolling_plan",
        "scenes",
    ):
        if not isinstance(normalized.get(field), list):
            normalized[field] = []
    for field in ("entry_state", "exit_state", "logic_hooks"):
        if not isinstance(normalized.get(field), dict):
            normalized[field] = {}
    normalized["logic_hooks"].setdefault("callback", "无")
    normalized["logic_hooks"].setdefault("setup", "无")
    return normalized


def validate_chapter_contract(
    outline: dict[str, Any], chapter_number: int
) -> list[str]:
    """Validate the minimum causal contract required before prose generation."""
    issues: list[str] = []
    try:
        generated_number = int(outline.get("chapter_number", 0) or 0)
    except (TypeError, ValueError):
        generated_number = 0
    if generated_number != chapter_number:
        issues.append("chapter_number 与当前章节不一致")
    if not str(outline.get("chapter_goal", "")).strip():
        issues.append("chapter_goal 为空")
    if len(outline.get("key_events", []) or []) < 2:
        issues.append("key_events 少于 2 个")
    scenes = outline.get("scenes", [])
    if not isinstance(scenes, list) or not 2 <= len(scenes) <= 5:
        issues.append("scenes 数量必须为 2-5 个")
    if not outline.get("entry_state"):
        issues.append("entry_state 为空")
    if not outline.get("exit_state"):
        issues.append("exit_state 为空")
    if len(outline.get("causal_chain", []) or []) < 2:
        issues.append("causal_chain 少于 2 步")
    for field in ("dramatic_question", "desire", "obstacle", "turn", "price_paid", "state_delta"):
        if not str(outline.get(field, "")).strip():
            issues.append(f"{field} 为空")
    if len(outline.get("tactics", []) or []) < 2:
        issues.append("tactics 少于 2 个")
    if not rolling_plan_covers(outline.get("rolling_plan"), chapter_number):
        issues.append("rolling_plan 未覆盖当前章节")
    return issues
