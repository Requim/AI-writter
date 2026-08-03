"""Per-chapter dramatic and continuity contract prompts."""

import json

from application.continuity import build_budgeted_context, build_story_bible
from application.prompts.outline_prompts import volume_for_chapter
from application.prompts.version import PROMPT_VERSION


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
    volume_json = json.dumps(volume_for_chapter(total_outline, chapter_index), ensure_ascii=False)
    total = int(total_outline.get("total_chapters", 0) or 0)
    word_target = _deterministic_word_target(chapter_index, total)
    retry_block = ""
    if validation_issues:
        retry_block = "\n【上一版未通过校验】\n- " + "\n- ".join(validation_issues)

    return f"""[PROMPT_VERSION:{PROMPT_VERSION}]
请为《{title}》生成第 {chapter_index} 章的剧情执行契约，类型为 {novel_type}。
只输出一个 JSON 对象，不要解释、Markdown 或思考过程。

【本卷目标】
{volume_json}

【静态故事圣经，不可违背】
{story_bible}

【前文连续性记忆】
{context}{retry_block}

【戏剧契约】
1. 本章只设一个 dramatic_question，并在结尾给出不可逆的阶段答案。
2. desire 是 POV 人物当下可行动的目标；obstacle 必须主动反制，不是天气或心情。
3. tactics 至少两次变化；turn 由行动引发，禁止依靠巧合或新角色突然解围。
4. price_paid 是本章真实支付的代价；state_delta 写清关系、信息、资源或立场的变化。
5. 依据本章复杂度选择 2-5 个场景，不固定数量；每个场景必须产生不同的转折或代价。
6. entry_state 继承前文；knowledge_boundaries 禁止角色获得作者视角信息。
7. callback 与 setup 只在因果需要的位置出现，不按固定百分比机械安放。
8. rolling_plan 从当前章开始，最多 5 章，不得超过全书第 {total or '?'} 章。
9. ending_mode 从 revelation、decision、reversal、arrival、deadline、emotional_shift 中选择，
   结尾必须来自本章行动后果，不得凭空制造悬念。

【JSON 结构】
{{
  "chapter_number": {chapter_index},
  "title": "章节标题",
  "chapter_goal": "本章在全书中的唯一功能",
  "pov_character": "本章视角人物",
  "dramatic_question": "本章结束前必须回答的问题",
  "desire": "视角人物当下目标",
  "obstacle": "主动阻碍及其目标",
  "tactics": ["第一次策略", "受阻后的新策略"],
  "turn": "改变局势或理解的关键转折",
  "price_paid": "为推进目标真实失去的东西",
  "state_delta": "与入场相比不可逆的状态变化",
  "ending_mode": "revelation|decision|reversal|arrival|deadline|emotional_shift",
  "key_events": ["事件1", "事件2"],
  "entry_state": {{"time": "", "location": "", "characters": [], "open_conflicts": []}},
  "causal_chain": ["因为...", "所以...", "导致..."],
  "state_changes": [{{"subject": "", "before": "", "after": "", "evidence_event": ""}}],
  "knowledge_boundaries": [{{"character": "", "known": [], "unknown": []}}],
  "continuity_constraints": ["不可违反的既有事实"],
  "scenes": [
    {{
      "location": "", "characters": ["人物及入场状态"],
      "scene_goal": "本场景可验证目标", "desire": "", "obstacle": "", "tactic": "",
      "events": {{"entry": "", "struggle": "", "result": ""}},
      "turn": "", "price_paid": "", "state_delta": "", "exit_hook": "",
      "sensory_details": {{"visual": "", "auditory": "", "olfactory_tactile": ""}},
      "dialogue_targets": {{"explicit": "", "implicit": ""}},
      "purpose": "本场景为何不可删除"
    }}
  ],
  "internal_monologue": "视角人物的认知变化：起点 → 触发 → 新认知",
  "logic_hooks": {{"callback": "已有伏笔及自然回收方式", "setup": "新伏笔及预计回收章节"}},
  "exit_state": {{"time": "", "location": "", "characters": [], "last_action": "", "next_pressure": ""}},
  "rolling_plan": [{{"chapter_number": {chapter_index}, "goal": "", "required_event": "", "state_delta": "", "callback_ids": [], "exit_hook": ""}}],
  "estimated_word_count": {word_target}
}}

scenes 必须包含 2-5 个完整对象；每个文本字段尽量控制在 100 个汉字内。"""


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
