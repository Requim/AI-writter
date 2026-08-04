"""角色设计提示词与结构化输出契约。"""

import json
from typing import Any

from application.prompts.template_loader import render_prompt


CHARACTER_DESIGN_SCHEMA = {
    "core_roles": "array",
    "supporting_characters": "array",
    "relationships": "array",
}


def build_character_design_prompt(
    novel_type: str,
    creative_brief: dict[str, Any],
    candidate_pool: list[dict[str, Any]],
    naming_preference: Any = None,
    feedback: str = "",
) -> str:
    """渲染只允许模型引用本次候选池的角色设计提示词。"""
    return render_prompt(
        "character_design/design.txt",
        novel_type=novel_type,
        creative_brief=json.dumps(creative_brief, ensure_ascii=False, indent=2),
        naming_preference=json.dumps(naming_preference or {}, ensure_ascii=False),
        candidate_pool=json.dumps(candidate_pool, ensure_ascii=False, indent=2),
        feedback=feedback or "无",
    )
