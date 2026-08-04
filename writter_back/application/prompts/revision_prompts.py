"""Prompt builders for bounded chapter revision modes."""

import json

from application.continuity import (
    build_budgeted_context,
    compact_story_bible,
)
from application.prompts.template_loader import render_prompt


PATCH_SCHEMA = {"edits": "array", "unresolved_issue_ids": "array"}

PATCH_TRIGGER_TYPES = {
    "consistency",
    "character",
    "padding",
    "pacing",
    "tension_gap",
    "plot_hole",
}
REFACTOR_TRIGGER_TYPES = {"power_system", "logic"}


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _continuity_block(continuity_context: str, story_bible: str) -> str:
    return render_prompt(
        "revision/continuity.txt",
        story_bible=compact_story_bible(story_bible, 2400) if story_bible else "无",
        continuity_context=build_budgeted_context(
            continuity_context,
            max_chars=3200,
        ),
    )


def _history_block(revision_history: str) -> str:
    if not revision_history:
        return ""
    return (
        "【此前修改记录】\n"
        f"{revision_history}\n"
        "避免重复修改已解决的问题，也不要回退之前的修正成果。"
    )


def build_user_instruction_revision_prompt(
    instructions: str,
    current_content: str,
    chapter_outline: dict,
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """生成执行用户定向修改要求的整章修订提示词。"""
    return render_prompt(
        "revision/user_instruction.txt",
        instructions=instructions,
        chapter_title=chapter_outline.get("title", ""),
        chapter_outline=_json(chapter_outline),
        current_content=current_content,
        continuity_block=_continuity_block(continuity_context, story_bible),
    )


def classify_revision_mode(issues: list) -> str:
    """有结构性 must_fix 问题时使用 refactor，否则使用 patch。"""
    for issue in issues:
        issue_type = issue.get("type", "")
        priority = issue.get("priority_action", "optional")
        if priority == "must_fix" and issue_type in REFACTOR_TRIGGER_TYPES:
            return "refactor"
    return "patch"


def build_patch_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_outline: dict,
    revision_history: str = "",
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """生成只返回可原子应用局部 edits 的修订提示词。"""
    return render_prompt(
        "revision/patch.txt",
        history_block=_history_block(revision_history),
        issues_text=issues_text,
        current_content=current_content,
        chapter_outline=_json(chapter_outline),
        continuity_block=_continuity_block(continuity_context, story_bible),
    )


def build_refactor_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_outline: dict,
    revision_history: str = "",
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """生成修复结构性问题的整章重构提示词。"""
    return render_prompt(
        "revision/refactor.txt",
        history_block=_history_block(revision_history),
        issues_text=issues_text,
        current_content=current_content,
        chapter_outline=_json(chapter_outline),
        continuity_block=_continuity_block(continuity_context, story_bible),
    )


def format_issues_for_prompt(issues: list) -> str:
    """把结构化问题转换为带证据与修复建议的紧凑文本。"""
    tags = {
        "must_fix": "【必须修正】",
        "optional": "【次要】",
        "can_ignore": "【可忽略】",
    }
    lines: list[str] = []
    for issue in issues:
        priority = issue.get("priority_action", "optional")
        fix = issue.get("suggested_fix_text", "")
        fix_text = f" 修改示例: {fix}" if fix else ""
        lines.append(
            f"- {tags.get(priority, '【次要】')}[ID={issue.get('issue_id', '')}]"
            f"[{issue.get('type', 'unknown')}]({issue.get('severity', 'low')}) "
            f"{issue.get('location', '')}: {issue.get('description', '')} "
            f"(原文证据: {issue.get('evidence', '')}) "
            f"(建议: {issue.get('suggestion', '')}){fix_text}"
        )
    return "\n".join(lines)


def build_revision_system_prompt() -> str:
    """返回修订任务的系统提示词。"""
    return render_prompt("revision/system.txt")


def build_expansion_prompt(
    current_content: str,
    chapter_outline: dict,
    target_words: int,
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """生成保持既有修复成果的正文扩写提示词。"""
    return render_prompt(
        "revision/expansion.txt",
        current_content=current_content,
        chapter_outline=_json(chapter_outline),
        continuity_block=_continuity_block(continuity_context, story_bible),
        target_words=target_words,
    )


PATCH_TEMPERATURE = 0.3
REFACTOR_TEMPERATURE = 0.55
REVISION_TEMPERATURE = 0.5
