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


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chapter_prompt_context(
    chapter_index: int,
    total_outline: dict,
    memory_context: str,
    plan_context: dict | None,
) -> dict:
    brief = total_outline.get("creative_brief", {})
    policy = brief.get("naming_policy", {}) if isinstance(brief, dict) else {}
    total = int(total_outline.get("total_chapters", 0) or 0)
    slot = plan_context.get("current_slot", {}) if isinstance(plan_context, dict) else {}
    target = int(slot.get("target_words", 0) or 0)
    return {
        "brief": brief,
        "context": build_budgeted_context(memory_context, max_chars=2800),
        "story_bible": build_story_bible(total_outline, max_chars=2600),
        "reserve": policy.get("reserve_pool", []) if isinstance(policy, dict) else [],
        "volume_json": json.dumps(
            volume_for_chapter(total_outline, chapter_index), ensure_ascii=False
        ),
        "total": total,
        "word_target": target or _deterministic_word_target(chapter_index, total),
    }


def _planning_contract(schema_version: int) -> tuple[str, str]:
    if schema_version < 5:
        return "8. rolling_plan 从当前章开始，最多 5 章，不得超过全书范围。", ""
    rule = (
        "8. rolling_plan 必须返回空数组；近期战术由服务端提供，不得另行规划。\n"
        "14. scenes 的 scene_index 必须从 1 连续编号；执行覆盖矩阵的每个必需 ID "
        "必须映射到真实 scene_index，且不得添加未声明 ID。"
    )
    field = (
        '  "chapter_execution_contract": {'
        '"obligation_coverage": {"obligation_id": 1}, '
        '"state_delta_coverage": {"state_delta_id": 1}, '
        '"setup_payoff_coverage": {"setup_or_payoff_id": 1}},'
    )
    return rule, field


def build_chapter_outline_prompt(
    chapter_index: int,
    novel_type: str,
    title: str,
    total_outline: dict,
    memory_context: str,
    validation_issues: list[str] | None = None,
    plan_context: dict | None = None,
    tactical_context: dict | None = None,
    execution_requirements: dict | None = None,
    schema_version: int = 2,
) -> str:
    """Generate a bounded dramatic contract before prose generation."""
    values = _chapter_prompt_context(
        chapter_index, total_outline, memory_context, plan_context
    )
    retry_block = ""
    if validation_issues:
        retry_block = "\n【上一版未通过校验】\n- " + "\n- ".join(validation_issues)
    planning_rule, contract_field = _planning_contract(schema_version)
    return render_prompt(
        "chapter/outline.txt",
        title=title,
        chapter_index=chapter_index,
        novel_type=novel_type,
        genre_strategy=genre_strategy_block(
            novel_type, values["brief"], "chapter_outline"
        ),
        volume_json=values["volume_json"],
        story_bible=values["story_bible"],
        memory_context=values["context"],
        retry_block=retry_block,
        total_chapters=values["total"] or "?",
        word_target=values["word_target"],
        reserved_name_pool=json.dumps(values["reserve"], ensure_ascii=False, indent=2),
        plan_context=_compact_json(plan_context or {}),
        tactical_context=_compact_json(tactical_context or {}),
        execution_requirements=_compact_json(execution_requirements or {}),
        planning_layer_rule=planning_rule,
        execution_contract_field=contract_field,
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
    "chapter_execution_contract": "object",
    "estimated_word_count": "integer",
}
