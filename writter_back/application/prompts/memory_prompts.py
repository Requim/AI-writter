"""分层记忆生成提示词（Plan A：S层故事状态 + L层章节摘要）"""

import json

from application.continuity import compact_text


def build_chapter_summary_prompt(chapter_title: str, chapter_content: str) -> str:
    """Generate an ending-aware L-layer summary from the complete chapter."""
    return (
        f"请用250字以内概括以下完整章节。\n"
        f"必须覆盖：关键因果链、人物状态变化、获得/失去的信息或物品、"
        f"已回收与新埋伏笔，以及结尾最后动作和下一章压力。禁止只概括开头。\n\n"
        f"章节标题：{chapter_title}\n"
        f"章节内容：{compact_text(chapter_content, 9000, tail_ratio=0.45)}\n"
        f'只输出 JSON：{{"summary":"章节摘要"}}'
    )


CHAPTER_SUMMARY_SCHEMA = {"summary": "string"}


def build_story_state_prompt(
    chapter_index: int,
    chapter_title: str,
    chapter_content: str,
    previous_state: str = "",
    chapter_outline: dict | None = None,
) -> str:
    """Merge the previous S-layer state with facts established by this chapter."""
    return f"""你是小说连续性管理员。请把“上一版累计故事状态”与本章已写成的事实合并，
输出新的累计状态 JSON。旧状态中未被本章明确改变的事实必须原样保留；不得根据细纲
臆造正文没有发生的事件，也不得删除仍未解决的冲突和伏笔。

【上一版累计故事状态】
{compact_text(previous_state, 4500, tail_ratio=0.35) if previous_state else "{}"}

【本章状态契约（仅用于核对，事实以正文为准）】
{json.dumps(chapter_outline or {}, ensure_ascii=False)}

【第{chapter_index + 1}章：{chapter_title}】
{compact_text(chapter_content, 9000, tail_ratio=0.45)}

【输出 JSON】
{{
  "timeline": {{"current_time": "", "elapsed": "", "sequence_notes": []}},
  "locations": [{{"character": "", "location": "", "since_chapter": {chapter_index + 1}}}],
  "characters": [{{
    "name": "", "physical_state": "", "emotional_state": "", "goal": "",
    "knowledge": [], "unknown_to_character": [], "inventory": [], "relationships": []
  }}],
  "open_conflicts": [{{"id": "", "description": "", "introduced_chapter": 1, "status": "open"}}],
  "foreshadowing": [{{
    "id": "", "description": "", "introduced_chapter": 1,
    "target_chapter": null, "status": "open|resolved"
  }}],
  "revealed_secrets": [],
  "unrevealed_secrets": [],
  "immutable_facts": [{{"fact": "", "source_chapter": 1}}],
  "last_transition": {{"last_action": "", "location": "", "next_pressure": ""}},
  "updated_through_chapter": {chapter_index + 1}
}}
只输出 JSON，不要 Markdown。"""


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
    "updated_through_chapter": "integer",
}


CHAPTER_SUMMARY_TEMPERATURE = 0.3
STORY_STATE_TEMPERATURE = 0.3
