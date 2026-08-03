"""Premise-grounded title generation prompts."""

import json
from typing import Any

from application.prompts.version import PROMPT_VERSION


TITLE_CANDIDATES_SCHEMA = {"candidates": "array"}


def build_title_prompt(novel_type: str, creative_brief: dict[str, Any] | None = None) -> str:
    """Generate scored title candidates that preserve the creative promise."""
    brief = json.dumps(creative_brief or {}, ensure_ascii=False, indent=2)
    return f"""[PROMPT_VERSION:{PROMPT_VERSION}]
你是一名小说命名策划。请基于创作简报，为「{novel_type}」小说生成 8 个书名候选。

【创作简报】
{brief}

【命名要求】
1. 每个书名必须指向 core_conflict、originality_anchor 或 protagonist_drive 中至少一项。
2. 候选需覆盖：反差、悬念、独特机制、人物关系四类，每类至少一个。
3. 禁止“逆天、传奇、纪元、归来”等可替换式词组，禁止照搬同类畅销书句式。
4. title 为 4-16 个汉字；hint 用一句话说明该书名承诺的具体故事。
5. 分别以 0-10 评价 specificity、conflict、originality、audience_fit；total_score 为四项总和。
6. 评分必须拉开差距，不能全部高分；候选顺序不代表优先级。

只输出以下 JSON，不要 Markdown 或解释：
{{
  "candidates": [
    {{
      "title": "",
      "hint": "",
      "category": "反差|悬念|独特机制|人物关系",
      "specificity": 0,
      "conflict": 0,
      "originality": 0,
      "audience_fit": 0,
      "total_score": 0
    }}
  ]
}}"""


TITLE_TEMPERATURE = 0.85
TITLE_TOP_P = 0.92
