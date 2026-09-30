"""Prompts and validation for work-specific genre strategy generation."""

import json
from typing import Any

from application.prompts.genre_strategy import genre_strategy_block
from application.prompts.template_loader import render_prompt
from service.value_objects.genre_profile import get_genre_profile

GENRE_STRATEGY_SCHEMA = {
    "reader_promise": "string",
    "plot_engine": "string",
    "style_constraints": "array",
    "chapter_requirements": "array",
    "review_dimensions": "array",
    "avoid_solutions": "array",
    "tone_guidance": "string",
    "originality_hooks": "array",
}

_TEXT = ("reader_promise", "plot_engine", "tone_guidance")
_LISTS = (
    "style_constraints",
    "chapter_requirements",
    "review_dimensions",
    "avoid_solutions",
    "originality_hooks",
)


def normalize_genre_strategy(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    result = {key: str(raw.get(key) or "").strip() for key in _TEXT}
    for key in _LISTS:
        values = raw.get(key, [])
        if isinstance(values, str):
            values = [values]
        result[key] = [str(item).strip() for item in values if str(item).strip()] if isinstance(values, list) else []
    return result


def validate_genre_strategy(value: Any) -> list[str]:
    """校验原始字段类型和长度，拒绝将异常对象转换为有效策略。"""
    strategy = value if isinstance(value, dict) else {}
    missing = [
        key for key in _TEXT
        if not isinstance(strategy.get(key), str) or not 1 <= len(strategy[key].strip()) <= 1000
    ]
    for key in _LISTS:
        items = strategy.get(key)
        if not isinstance(items, list) or not 1 <= len(items) <= 12:
            missing.append(key)
        elif any(not isinstance(item, str) or not 1 <= len(item.strip()) <= 500 for item in items):
            missing.append(key)
    return missing


def static_genre_strategy(novel_type: str) -> dict[str, Any]:
    """为旧 checkpoint 提供无模型的兼容策略。"""
    profile = get_genre_profile(novel_type)
    axes = profile.prompt_axes if profile else {}
    return normalize_genre_strategy({
        "reader_promise": axes.get("reader_promise", "持续兑现题材核心阅读承诺。"),
        "plot_engine": axes.get("plot_engine", "让人物目标、限制和后果推动剧情。"),
        "style_constraints": [axes.get("style_constraints", "使用具体行动和可验证细节。")],
        "chapter_requirements": [axes.get("chapter_focus", "每章产生明确状态变化。")],
        "review_dimensions": [axes.get("review_focus", "检查因果、连续性和题材承诺。")],
        "avoid_solutions": axes.get("avoid_solutions", ["无铺垫反转", "无代价解决"]),
        "tone_guidance": "遵循既有作品风格，避免改变历史正文语气。",
        "originality_hooks": ["沿用既有故事设定发展人物选择与代价。"],
    })


def build_genre_strategy_prompt(
    novel_type: str,
    genre_context: dict[str, Any] | None = None,
    user_requirements: str = "",
    work_context: dict[str, Any] | None = None,
) -> str:
    context = genre_context if isinstance(genre_context, dict) else {}
    return render_prompt(
        "genre_strategy/generate.txt",
        novel_type=novel_type,
        genre_context=json.dumps(context, ensure_ascii=False, indent=2),
        base_strategy=genre_strategy_block(novel_type, {"genre_context": context}, "creative_brief"),
        user_requirements=user_requirements or "未提供",
        work_context=json.dumps(work_context or {}, ensure_ascii=False, indent=2),
    )
