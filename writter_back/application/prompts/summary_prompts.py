"""简介生成提示词"""

import json
from typing import Any

from application.prompts.version import PROMPT_VERSION

SUMMARY_SCHEMA = {"reader_blurb": "string", "editorial_brief": "string"}


def build_summary_prompt(
    novel_type: str,
    title: str,
    story_hint: str = "",
    creative_brief: dict[str, Any] | None = None,
) -> str:
    """
    优化后的简介生成提示词：结构化四段式 + 一句话简介 + 拒绝废话
    story_hint 由书名生成节点联动传入，形成"类型→书名→简介→总纲"的闭环
    """
    hint_section = f"\n【书名核心卖点】\n书名背后的故事线提示：{story_hint}" if story_hint else ""

    brief = json.dumps(creative_brief or {}, ensure_ascii=False, indent=2)
    return f"""[PROMPT_VERSION:{PROMPT_VERSION}]
你是一位资深小说编辑。请同时生成面向读者的封面文案，以及供后续总纲规划使用的内部简介。

【基础信息】
书名：《{title}》
类型：{novel_type}{hint_section}

【创作简报（不可改写）】
{brief}

【reader_blurb 要求】
1. 250-350 字，不使用模块标题、Markdown 或策划术语。
2. 依次建立背景、主角困境、独特机制与升级风险，结尾留下具体悬念。
3. 同时兑现 core_premise、core_conflict、reader_promise 和 originality_anchor，
   但不要直接回答 theme_question。

【editorial_brief 要求】
1. 400-700 字，明确主角目标、对手目标、核心机制、代价、升级路径和预期结局方向。
2. 使用内部策划语言，给总纲足够的因果约束；不得引入创作简报之外的万能解法。

【风格引导】
- 拒绝废话：严禁使用"在XX的世界里"、"他能否成就传奇"、"这一次，他要夺回属于自己的一切"等万金油废话。
- 画面感：使用具有动感和压迫感的词汇。
- 逻辑钩子：简介的结尾必须引发读者对剧情走向的好奇。

只输出以下 JSON，不要 Markdown 或额外解释：
{{
  "reader_blurb": "面向读者的封面文案",
  "editorial_brief": "供总纲规划使用的内部简介"
}}
"""


SUMMARY_TEMPERATURE = 0.8
SUMMARY_TOP_P = 0.92
