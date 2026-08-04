"""Per-chapter dramatic and continuity contract prompts."""

import json

from application.continuity import build_budgeted_context, build_story_bible
from application.prompts.genre_strategy import genre_strategy_block
from application.prompts.outline_prompts import volume_for_chapter
from application.prompts.template_loader import render_prompt


def _deterministic_word_target(chapter_number: int, total_chapters: int) -> int:
    """Return a reproducible target while reserving room for structural peaks."""
    if chapter_number in {1, total_chapters}:
        return 4800
    return 4200 + (chapter_number % 3) * 200


def build_chapter_outline_prompt(
    chapter_index: int,
    novel_type: str,
    title: str,
    total_outline: dict,
    memory_context: str,
    validation_issues: list[str] | None = None,
) -> str:
    """Generate a bounded dramatic contract before prose generation."""
    context = build_budgeted_context(memory_context, max_chars=2800)
    story_bible = build_story_bible(total_outline, max_chars=2600)
    brief = total_outline.get("creative_brief", {})
    policy = brief.get("naming_policy", {}) if isinstance(brief, dict) else {}
    reserve = policy.get("reserve_pool", []) if isinstance(policy, dict) else []
    volume_json = json.dumps(volume_for_chapter(total_outline, chapter_index), ensure_ascii=False)
    total = int(total_outline.get("total_chapters", 0) or 0)
    word_target = _deterministic_word_target(chapter_index, total)
    retry_block = ""
    if validation_issues:
        retry_block = "\n【上一版未通过校验】\n- " + "\n- ".join(validation_issues)

    return render_prompt(
        "chapter/outline.txt",
        title=title,
        chapter_index=chapter_index,
        novel_type=novel_type,
        genre_strategy=genre_strategy_block(novel_type, brief, "chapter_outline"),
        volume_json=volume_json,
        story_bible=story_bible,
        memory_context=context,
        retry_block=retry_block,
        total_chapters=total or "?",
        word_target=word_target,
        reserved_name_pool=json.dumps(reserve, ensure_ascii=False, indent=2),
    )


CHAPTER_OUTLINE_SCHEMA = {
    "chapter_number": "integer",
    "title": "string",
    "chapter_goal": "string",
    "pov_character": "string",
    "dramatic_question": "string",
    "desire": "string",
    "obstacle": "string",
    "tactics": "array",
    "turn": "string",
    "price_paid": "string",
    "state_delta": "string",
    "ending_mode": "string",
    "narrative_pattern": "object",
    "genre_contract": "object",
    "new_long_term_characters": "array",
    "key_events": "array",
    "entry_state": "object",
    "causal_chain": "array",
    "state_changes": "array",
    "knowledge_boundaries": "array",
    "continuity_constraints": "array",
    "scenes": "array",
    "internal_monologue": "string",
    "logic_hooks": "object",
    "exit_state": "object",
    "rolling_plan": "array",
    "estimated_word_count": "integer",
}
