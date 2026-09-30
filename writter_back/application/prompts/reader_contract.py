"""章节级读者推进契约的兼容归一化与提示词渲染。"""

from __future__ import annotations

import json
from typing import Any

from application.prompts.template_loader import render_prompt


_FIELDS = (
    "promise",
    "opening_hook",
    "immediate_goal",
    "immediate_risk",
    "reader_question",
    "chapter_payoff",
    "next_pressure",
)


def _text(value: Any, fallback: str) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    text = str(value or "").strip()
    return text or fallback


def _fallbacks(outline: dict[str, Any]) -> dict[str, str]:
    scenes = outline.get("scenes") if isinstance(outline.get("scenes"), list) else []
    first = scenes[0] if scenes and isinstance(scenes[0], dict) else {}
    events = first.get("events") if isinstance(first.get("events"), dict) else {}
    genre = outline.get("genre_contract")
    genre = genre if isinstance(genre, dict) else {}
    hooks = outline.get("logic_hooks")
    hooks = hooks if isinstance(hooks, dict) else {}
    exit_state = outline.get("exit_state")
    exit_state = exit_state if isinstance(exit_state, dict) else {}
    return {
        "promise": str(genre.get("promise") or outline.get("chapter_goal") or "推进本章核心问题"),
        "opening_hook": str(events.get("entry") or first.get("scene_goal") or outline.get("chapter_goal") or "人物立即面对当前问题"),
        "immediate_goal": str(outline.get("desire") or first.get("desire") or "处理眼前问题"),
        "immediate_risk": str(outline.get("obstacle") or outline.get("price_paid") or "行动失败会付出代价"),
        "reader_question": str(outline.get("dramatic_question") or outline.get("turn") or "人物的选择会带来什么后果"),
        "chapter_payoff": str(outline.get("turn") or outline.get("state_delta") or "局势发生不可逆变化"),
        "next_pressure": str(hooks.get("setup") or exit_state.get("next_pressure") or outline.get("state_delta") or "新的压力延续到下一章"),
    }


def normalize_reader_contract(outline: dict[str, Any], chapter_number: int) -> dict[str, str]:
    """为旧细纲补齐契约字段，但不把补齐结果当作质量验收。"""
    raw = outline.get("reader_contract")
    raw = raw if isinstance(raw, dict) else {}
    defaults = _fallbacks(outline)
    result = {field: _text(raw.get(field), defaults[field]) for field in _FIELDS}
    result["chapter_number"] = str(chapter_number)
    return result


def build_reader_contract_prompt(outline: dict[str, Any], chapter_number: int) -> str:
    contract = normalize_reader_contract(outline, chapter_number)
    first_rules = (
        "首章必须在前500字内让读者看懂谁、在哪里、遇到了什么具体麻烦；"
        "主角要完成一个可见动作，留下一个有指向性的未解问题和立即风险。"
        if chapter_number == 1
        else "本章开头必须承接上一章压力，并在前800字内让POV人物采取行动或作出判断。"
    )
    return render_prompt(
        "chapter/reader_contract.txt",
        include_active_rules=False,
        chapter_number=chapter_number,
        contract=json.dumps(contract, ensure_ascii=False, indent=2),
        first_chapter_rules=first_rules,
    )


def reader_contract_outline_rules(chapter_number: int) -> str:
    """Return concise planning rules without exposing prose-only instructions."""
    if chapter_number == 1:
        return (
            "reader_contract 必须具体写出 opening_hook、immediate_goal、immediate_risk 和 reader_question；"
            "前500字内要能完成定位、触发事件和一次人物动作，禁止先写大段背景。"
        )
    return (
        "reader_contract 必须写出本章承接的压力、POV人物的立即目标、可见风险、读者追问和章末后续压力；"
        "开头800字内要有行动或明确判断。"
    )
