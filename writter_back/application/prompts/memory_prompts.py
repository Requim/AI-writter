"""分层记忆生成提示词（Plan A：S层故事状态 + L层章节摘要）"""

import json

from application.continuity import compact_text
from application.prompts.template_loader import render_prompt


def build_chapter_summary_prompt(chapter_title: str, chapter_content: str) -> str:
    """Generate an ending-aware L-layer summary from the complete chapter."""
    return render_prompt(
        "memory/chapter_summary.txt",
        chapter_title=chapter_title,
        chapter_content=compact_text(chapter_content, 9000, tail_ratio=0.45),
    )


CHAPTER_SUMMARY_SCHEMA = {"summary": "string", "narrative_pattern": "object"}


def build_story_state_prompt(
    chapter_index: int,
    chapter_title: str,
    chapter_content: str,
    previous_state: str = "",
    chapter_outline: dict | None = None,
) -> str:
    """Merge the previous S-layer state with facts established by this chapter."""
    chapter_number = chapter_index + 1
    return render_prompt(
        "memory/story_state.txt",
        previous_state=compact_text(previous_state, 4500, tail_ratio=0.35) if previous_state else "{}",
        chapter_outline=json.dumps(chapter_outline or {}, ensure_ascii=False),
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        chapter_content=compact_text(chapter_content, 9000, tail_ratio=0.45),
    )


STORY_STATE_SCHEMA = {
    "timeline": "object",
    "locations": "array",
    "characters": "array",
    "open_conflicts": "array",
    "foreshadowing": "array",
    "revealed_secrets": "array",
    "unrevealed_secrets": "array",
    "immutable_facts": "array",
    "last_transition": "object",
    "recent_narrative_patterns": "array",
    "updated_through_chapter": "integer",
}


CHAPTER_SUMMARY_TEMPERATURE = 0.3
STORY_STATE_TEMPERATURE = 0.3
