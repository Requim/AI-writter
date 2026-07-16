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


def build_story_bible(total_outline: dict[str, Any], max_chars: int = 3200) -> str:
    """Create a stable, deterministic canon block from the macro outline."""
    bible = {
        "world_rules": total_outline.get("story_background", ""),
        "main_characters": total_outline.get("main_characters", []),
        "main_plot": total_outline.get("main_plot", {}),
        "writing_style": total_outline.get("writing_style", ""),
    }
    return compact_text(
        json.dumps(bible, ensure_ascii=False, indent=2),
        max_chars,
        tail_ratio=0.25,
    )


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
    if not isinstance(scenes, list) or len(scenes) < 3:
        issues.append("scenes 少于 3 个")
    if not outline.get("entry_state"):
        issues.append("entry_state 为空")
    if not outline.get("exit_state"):
        issues.append("exit_state 为空")
    if len(outline.get("causal_chain", []) or []) < 2:
        issues.append("causal_chain 少于 2 步")
    if not rolling_plan_covers(outline.get("rolling_plan"), chapter_number):
        issues.append("rolling_plan 未覆盖当前章节")
    return issues
