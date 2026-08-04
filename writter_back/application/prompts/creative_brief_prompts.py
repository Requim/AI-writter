"""Creative-brief prompt and deterministic compatibility helpers."""

import json
from typing import Any

from application.prompts.genre_strategy import genre_strategy_block
from application.prompts.template_loader import render_prompt


CREATIVE_BRIEF_SCHEMA = {
    "core_premise": "string",
    "protagonist_drive": "string",
    "core_conflict": "string",
    "theme_question": "string",
    "reader_promise": "string",
    "tone": "string",
    "originality_anchor": "string",
    "setting_context": "object",
    "naming_preference": "string",
    "style_fingerprint": "string",
    "trope_contract": "object",
    "genre_context": "object",
    "content_boundaries": "array",
}

_REQUIRED_TEXT_FIELDS = (
    "core_premise",
    "protagonist_drive",
    "core_conflict",
    "theme_question",
    "reader_promise",
    "tone",
    "originality_anchor",
)
_OPTIONAL_TEXT_FIELDS = ("naming_preference", "style_fingerprint")
_OBJECT_FIELDS = ("setting_context", "trope_contract")
_GENRE_CONTEXT_FIELDS = (
    "main_type",
    "subgenre",
    "reader_experience",
    "narrative_pace",
)


def normalize_creative_brief(value: Any) -> dict[str, Any]:
    """Normalize model or user input into the stable creative-brief contract."""
    raw = value if isinstance(value, dict) else {}
    text_fields = (*_REQUIRED_TEXT_FIELDS, *_OPTIONAL_TEXT_FIELDS)
    brief = {field: str(raw.get(field, "") or "").strip() for field in text_fields}
    for field in _OBJECT_FIELDS:
        brief[field] = raw.get(field, {}) if isinstance(raw.get(field), dict) else {}
    context = raw.get("genre_context", {})
    brief["genre_context"] = {
        field: str(context.get(field) or "").strip()
        for field in _GENRE_CONTEXT_FIELDS
        if isinstance(context, dict) and str(context.get(field) or "").strip()
    }
    boundaries = raw.get("content_boundaries", [])
    if isinstance(boundaries, str):
        boundaries = [item.strip() for item in boundaries.split("；") if item.strip()]
    if not isinstance(boundaries, list):
        boundaries = []
    brief["content_boundaries"] = [str(item).strip() for item in boundaries if str(item).strip()]
    return brief


def validate_creative_brief(brief: dict[str, Any]) -> list[str]:
    """Return missing creative-contract fields."""
    return [field for field in _REQUIRED_TEXT_FIELDS if not str(brief.get(field, "")).strip()]


def build_legacy_creative_brief(
    novel_type: str,
    title: str,
    summary: str,
    outline: dict[str, Any],
) -> dict[str, Any]:
    """Create a no-LLM compatibility brief for an already planned legacy novel."""
    main_plot = outline.get("main_plot", {})
    plot_text = json.dumps(main_plot, ensure_ascii=False) if main_plot else summary
    background = str(outline.get("story_background", "") or "")
    style = str(outline.get("writing_style", "") or "")
    premise = summary or f"《{title}》围绕既定主线展开"
    return normalize_creative_brief(
        {
            "core_premise": premise,
            "protagonist_drive": premise,
            "core_conflict": plot_text or premise,
            "theme_question": "人物为达成目标愿意付出什么代价",
            "reader_promise": f"持续兑现{novel_type}类型的冲突、变化与情绪回报",
            "tone": style or "遵循既有正文风格",
            "originality_anchor": background[:240] or premise,
            "setting_context": {},
            "naming_preference": "服从时代、地域和家庭背景",
            "style_fingerprint": style or "遵循既有正文风格",
            "trope_contract": {},
            "content_boundaries": [],
        }
    )


def build_creative_brief_prompt(
    novel_type: str,
    title: str = "",
    summary: str = "",
    seed: dict[str, Any] | None = None,
    feedback: str = "",
) -> str:
    """Build the premise-first contract used by all downstream prompts."""
    seed_json = json.dumps(seed or {}, ensure_ascii=False, indent=2)
    feedback_block = f"\n【本次修改要求】\n{feedback}" if feedback else ""
    return render_prompt(
        "creative_brief/brief.txt",
        novel_type=novel_type,
        title=title or "未提供",
        summary=summary or "未提供",
        seed_json=seed_json,
        genre_strategy=genre_strategy_block(novel_type, seed or {}, "creative_brief"),
        feedback_block=feedback_block,
    )
