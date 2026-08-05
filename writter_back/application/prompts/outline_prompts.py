"""Prompts and validation for the macro novel outline."""

import json
from math import ceil

from typing import Any

from application.prompts.genre_strategy import genre_strategy_block
from application.prompts.template_loader import render_prompt


OUTLINE_SCHEMA: dict[str, str] = {
    "story_background": "string",
    "main_characters": "array",
    "main_plot": "object",
    "antagonist_plan": "string",
    "truth_reveal_ladder": "array",
    "cost_curve": "array",
    "relationship_turns": "array",
    "writing_style": "string",
    "total_chapters": "integer",
    "volumes": "array",
}

# Kept as an alias for callers that still refer to the old two-phase contract.
MACRO_ONLY_SCHEMA = OUTLINE_SCHEMA


def build_outline_prompt(
    novel_type: str,
    title: str,
    summary: str,
    target_total_chapters: int | None = None,
    requested_writing_style: str | None = None,
    creative_brief: dict[str, Any] | None = None,
    main_characters: list[dict[str, Any]] | None = None,
) -> str:
    """Build a bounded macro-outline prompt without per-chapter output."""
    chapter_requirement = (
        f"固定为用户计划的 {target_total_chapters} 章，不得擅自增加或减少。"
        if target_total_chapters
        else "根据题材选择 120-200 章，不要固定为某一个数字。"
    )
    style_requirement = (
        f"以用户指定的“{requested_writing_style}”为强制基调，并扩展为叙事视角、节奏、语言、对话和氛围规范。"
        if requested_writing_style
        else "明确叙事视角、节奏、语言基调、对话风格和氛围。"
    )
    volume_requirement = (
        f"精确规划 {min(8, max(1, ceil(target_total_chapters / 25)))} 卷，"
        "每卷不超过 25 章，连续覆盖全书。"
        if target_total_chapters
        else "规划 5-8 卷且每卷不超过 25 章，连续覆盖全书。"
    )
    characters = main_characters or []
    if characters:
        requirement = "逐项复制已确认角色；只能补充人物弧阶段和分卷职责，不得换名、删人或重写底层设定。"
        characters_json = json.dumps(characters, ensure_ascii=False, indent=2)
    else:
        requirement = "未提供已确认角色时生成 6-10 名角色，保持简介既有人名；每人包含姓名、性格、目标、冲突对象和关系标签。"
        characters_json = '[{"姓名":"","性格":"","目标":"","冲突对象":"","关系标签":""}]'
    return render_prompt(
        "outline/macro.txt",
        novel_type=novel_type,
        title=title,
        summary=summary,
        creative_brief=json.dumps(creative_brief or {}, ensure_ascii=False, indent=2),
        genre_strategy=genre_strategy_block(novel_type, creative_brief, "outline"),
        main_characters=json.dumps(characters, ensure_ascii=False, indent=2) if characters else "未提供",
        character_requirement=requirement,
        main_characters_json=characters_json,
        style_requirement=style_requirement,
        chapter_requirement=chapter_requirement,
        volume_requirement=volume_requirement,
    )


def volume_for_chapter(outline: dict[str, Any], chapter_number: int) -> dict[str, Any]:
    """Return the macro volume containing a one-based chapter number."""
    for volume in outline.get("volumes", []):
        try:
            start = int(volume.get("start_chapter", 0))
            end = int(volume.get("end_chapter", 0))
        except (TypeError, ValueError):
            continue
        if start <= chapter_number <= end:
            return volume
    return {}


def validate_outline(outline: dict[str, Any]) -> dict[str, Any]:
    """Validate only the macro contract; chapter plans are intentionally absent."""
    issues: list[str] = []
    fatal: list[str] = []

    if not str(outline.get("story_background", "")).strip():
        fatal.append("story_background 为空")
    if not isinstance(outline.get("main_plot"), dict) or not outline.get("main_plot"):
        fatal.append("main_plot 为空")
    if not str(outline.get("writing_style", "")).strip():
        fatal.append("writing_style 为空")

    characters = outline.get("main_characters", [])
    if not isinstance(characters, list) or len(characters) < 3:
        fatal.append("main_characters 不足 3 人")
    elif len(characters) < 6:
        issues.append(f"核心角色少于 6 人（当前 {len(characters)} 人）")

    try:
        total = int(outline.get("total_chapters", 0))
    except (TypeError, ValueError):
        total = 0
    if total <= 0:
        fatal.append("total_chapters 无效")
    elif not 30 <= total <= 300:
        issues.append(f"total_chapters={total} 超出建议范围 30-300")

    volumes = outline.get("volumes", [])
    if not isinstance(volumes, list) or not volumes:
        fatal.append("volumes 为空")
    elif total > 0:
        first_start = volumes[0].get("start_chapter")
        last_end = volumes[-1].get("end_chapter")
        if first_start != 1 or last_end != total:
            issues.append("volumes 未完整覆盖第1章到 total_chapters")

    if "chapters" in outline:
        issues.append("已忽略总纲中多余的 chapters 字段")

    return {
        "valid": not fatal,
        "issues": [*fatal, *issues],
        "fatal_issues": fatal,
    }
