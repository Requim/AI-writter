"""Compact per-chapter continuity contract prompts."""

import json
import random

from application.continuity import build_budgeted_context, build_story_bible
from application.prompts.outline_prompts import volume_for_chapter


def build_chapter_outline_prompt(
    chapter_index: int,
    novel_type: str,
    title: str,
    total_outline: dict,
    memory_context: str,
    validation_issues: list[str] | None = None,
) -> str:
    """Generate a compact causal contract that can be returned before proxy timeout."""
    context = build_budgeted_context(memory_context, max_chars=2800)
    story_bible = build_story_bible(total_outline, max_chars=2400)
    volume = volume_for_chapter(total_outline, chapter_index)
    volume_json = json.dumps(volume, ensure_ascii=False)
    word_target = random.randint(3500, 5000)
    retry_block = ""
    if validation_issues:
        retry_block = (
            "\n【上一版未通过校验，必须修复】\n- "
            + "\n- ".join(validation_issues)
        )

    return f"""请为《{title}》生成第 {chapter_index} 章的紧凑剧情契约，类型为 {novel_type}。
只输出一个 JSON 对象，不要解释、Markdown 或思考过程。

【本卷目标】
{volume_json}

【静态故事圣经，不可违背】
{story_bible}

【前文连续性记忆】
{context}
{retry_block}

【硬性规则】
1. 本章必须推进本卷 core_conflict 或 main_character_arc，不得提前完成 climax_event。
2. 固定输出 3 个场景。每个文本字段控制在 80 个汉字以内，避免空泛描写。
3. causal_chain 至少 3 步，必须形成“因为 A → 所以 B → 导致 C”的因果关系。
4. entry_state 必须继承前文；exit_state、state_changes 必须能在正文中验证。
5. knowledge_boundaries 明确角色已知和未知，禁止角色获得作者视角信息。
6. callback 回收已有伏笔；setup 新建伏笔时给出稳定 ID 和预计回收章节。
7. rolling_plan 输出从当前章开始、最多 5 章的轻量节拍，不得超过全书第
   {total_outline.get('total_chapters', '?')} 章；已有 P 层规划没有冲突时应继续沿用。
8. 正文字数目标约 {word_target} 字，三个场景承担不同事件，禁止重复同一信息。

【JSON 结构】
{{
  "chapter_number": {chapter_index},
  "title": "章节标题",
  "chapter_goal": "本章唯一推进目标",
  "key_events": ["事件1", "事件2", "事件3"],
  "entry_state": {{"time": "", "location": "", "characters": [], "open_conflicts": []}},
  "causal_chain": ["因为...", "所以...", "导致..."],
  "state_changes": [{{"subject": "", "before": "", "after": "", "evidence_event": ""}}],
  "knowledge_boundaries": [{{"character": "", "known": [], "unknown": []}}],
  "continuity_constraints": ["不可违反事实1", "不可违反事实2", "不可违反事实3"],
  "scenes": [
    {{
      "location": "",
      "characters": ["人物及进入场景时的状态"],
      "events": {{"entry": "", "struggle": "", "result": ""}},
      "sensory_details": {{"visual": "", "auditory": "", "olfactory_tactile": ""}},
      "dialogue_targets": {{"explicit": "", "implicit": ""}},
      "purpose": "该场景产生的不可逆变化"
    }}
  ],
  "internal_monologue": "主角心理变化：起点 → 转折 → 终点",
  "logic_hooks": {{
    "callback": "伏笔ID/来源章节/本章如何回收；没有则写无",
    "setup": "新伏笔ID/内容/预计回收章节；没有则写无"
  }},
  "exit_state": {{
    "time": "", "location": "", "characters": [],
    "last_action": "", "next_pressure": ""
  }},
  "rolling_plan": [
    {{
      "chapter_number": {chapter_index}, "goal": "", "required_event": "",
      "state_delta": "", "callback_ids": [], "exit_hook": ""
    }}
  ],
  "estimated_word_count": {word_target}
}}

scenes 数组必须恰好包含 3 个完整对象；rolling_plan 每章只写一个核心事件。"""


CHAPTER_OUTLINE_SCHEMA = {
    "chapter_number": "integer",
    "title": "string",
    "chapter_goal": "string",
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
