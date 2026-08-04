"""简介生成提示词"""

import json
from typing import Any

from application.prompts.template_loader import render_prompt

SUMMARY_SCHEMA = {"reader_blurb": "string", "editorial_brief": "string"}


def build_summary_prompt(
    novel_type: str,
    title: str,
    story_hint: str = "",
    creative_brief: dict[str, Any] | None = None,
    main_characters: list[dict[str, Any]] | None = None,
) -> str:
    """
    优化后的简介生成提示词：结构化四段式 + 一句话简介 + 拒绝废话
    story_hint 由书名生成节点联动传入，形成"类型→书名→简介→总纲"的闭环
    """
    hint_section = f"\n【书名核心卖点】\n书名背后的故事线提示：{story_hint}" if story_hint else ""

    return render_prompt(
        "summary/summary.txt",
        title=title,
        novel_type=novel_type,
        hint_section=hint_section,
        creative_brief=json.dumps(creative_brief or {}, ensure_ascii=False, indent=2),
        main_characters=json.dumps(main_characters or [], ensure_ascii=False, indent=2),
    )


SUMMARY_TEMPERATURE = 0.8
SUMMARY_TOP_P = 0.92
