"""Prompt rendering helpers for genre-specific writing strategy."""

from __future__ import annotations

from typing import Any

from service.value_objects.genre_profile import (
    GENRE_PROFILES,
    GenreOption,
    GenreProfile,
    PACE_OPTIONS,
    get_genre_profile,
)


_STAGE_FOCUS = {
    "creative_brief": "生成 reader_promise、trope_contract 与 style_fingerprint 时优先服从题材承诺。",
    "outline": "全书结构要让分卷冲突持续兑现题材快感，并避免通用换皮。",
    "chapter_outline": "本章契约要写明题材快感如何被行动、信息或关系变化兑现。",
    "chapter_writer": "正文要把题材策略落到可见行动、细节、对白和结尾后果。",
    "reflection": "审读时额外检查题材承诺、母题变体和禁用解法是否被违反。",
}


def _context(creative_brief: dict[str, Any] | None) -> dict[str, str]:
    raw = creative_brief.get("genre_context") if isinstance(creative_brief, dict) else {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: str(raw.get(key) or "").strip()
        for key in ("main_type", "subgenre", "reader_experience", "narrative_pace")
        if str(raw.get(key) or "").strip()
    }


def _profile(novel_type: str, ctx: dict[str, str]) -> GenreProfile:
    profile = get_genre_profile(ctx.get("main_type", "")) or get_genre_profile(novel_type)
    return profile or GENRE_PROFILES[0]


def _option_label(options: tuple[GenreOption, ...], value: str) -> str:
    matched = next((item for item in options if item.value == value), None)
    return (matched or options[0]).label if options else value


def _avoid_text(values: object) -> str:
    if isinstance(values, list):
        return "、".join(str(item) for item in values if str(item).strip()) or "无"
    return str(values or "无")


def genre_strategy_block(
    novel_type: str,
    creative_brief: dict[str, Any] | None = None,
    stage: str = "creative_brief",
) -> str:
    """Render a compact genre strategy block for a prompt stage."""
    ctx = _context(creative_brief)
    profile = _profile(novel_type, ctx)
    subgenre = _option_label(profile.subgenres, ctx.get("subgenre", ""))
    reader = _option_label(profile.reader_experiences, ctx.get("reader_experience", ""))
    pace = _option_label(PACE_OPTIONS, ctx.get("narrative_pace", "balanced"))
    axes = profile.prompt_axes
    return "\n".join(
        [
            "【题材策略】",
            f"主类型：{profile.label}（{profile.value}）",
            f"子类型：{subgenre}",
            f"读者快感：{reader}",
            f"叙事节奏：{pace}",
            f"题材承诺：{axes.get('reader_promise', '')}",
            f"结构引擎：{axes.get('plot_engine', '')}",
            f"阶段重点：{_STAGE_FOCUS.get(stage, _STAGE_FOCUS['creative_brief'])}",
            f"行文边界：{axes.get('style_constraints', '')}",
            f"章节检查：{axes.get('chapter_focus', '')}",
            f"审读检查：{axes.get('review_focus', '')}",
            f"禁用解法：{_avoid_text(axes.get('avoid_solutions'))}",
        ]
    )
