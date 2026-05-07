"""反思检查提示词"""

import json


def build_reflection_prompt(
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
) -> str:
    """反思检查的提示词"""
    return f"""
请对以下章节内容进行全面的反思检查，重点检查：
1. 逻辑一致性（与总纲领是否一致）
2. 情节漏洞（plot holes）
3. 人物行为是否合理
4. 与前后文是否连贯
5. 是否达到章节细纲的所有要求
6. 是否存在注水内容（字数是否真实有效）
7. 字数是否在3000-6000字之间

章节内容（前1500字摘要）：
{chapter_content[:1500]}...

章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

总纲领主角信息：
{json.dumps(main_characters, ensure_ascii=False)}

前文上下文（摘要）：
{memory_context[:500] if memory_context else '无'}

输出JSON格式：
{{
    "passed": true或false,
    "issues": [
        {{
            "type": "logic|consistency|plot_hole|character|padding|word_count",
            "severity": "low|medium|high",
            "location": "具体位置（章节/段落）",
            "description": "问题描述",
            "evidence": "原文引用（50字内）",
            "suggestion": "修正建议"
        }}
    ],
    "overall_quality_score": 0.0-1.0之间的数字,
    "word_count": {content_length},
    "is_valid_word_count": true或false
}}
"""


REFLECTION_SCHEMA = {
    "passed": "boolean",
    "issues": "array",
    "overall_quality_score": "number",
    "word_count": "integer",
    "is_valid_word_count": "boolean",
}
