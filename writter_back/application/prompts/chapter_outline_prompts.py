"""章节细纲生成提示词"""

import random


def build_chapter_outline_prompt(
    chapter_index: int,
    novel_type: str,
    title: str,
    chapter_theme: str,
    key_events: list,
    memory_context: str,
) -> str:
    """生成章节细纲的提示词"""
    theme_str = chapter_theme or '未指定'
    events_str = str(key_events) if key_events else "[]"
    ctx = memory_context[:1200] if memory_context else "无"
    word_target = random.randint(3500, 5500)

    return f"""请为第 {chapter_index} 章生成深度细纲。本细纲必须具备极高的内容密度，足以支撑 3000-6000 字的正文创作。

【本章上下文】
书名/类型：{title} / {novel_type}
本章主题/事件：{theme_str} | {events_str}
前文提要：{ctx}

【生成约束】：
1. 场景丰满度：本章必须拆解为 3-5 个具体场景。每个场景需包含"环境渲染"、"心理博弈"与"动作细节"。
2. 对话张力：对话严禁废话，必须包含潜台词（Subtext）或信息层面的交锋。
3. 逻辑衔接：必须显式说明本章如何承接前文的压力，并为后续主线制造新的悬念（Hooks）。
4. 细节支撑：每个场景需列出至少 3 个具体的细节描写建议（如：特定的气味、某个小动作、光影变化）。

【输出JSON格式】：
{{
    "chapter_number": {chapter_index},
    "title": "富有感染力的章节标题",
    "word_count_distribution": "建议配比：场景1(1500字), 场景2(2000字)...",
    "scenes": [
        {{
            "location": "场景地点",
            "characters": ["涉及人物及当前情感状态"],
            "events": ["情节A -> 转折B -> 结果C"],
            "sensory_details": ["视觉/听觉等具体描写素材"],
            "dialogue_targets": ["对话要达到的目的", "关键金句/潜台词"],
            "purpose": "该场景在全书逻辑中的必要性"
        }}
    ],
    "internal_monologue": "主角在本章的核心心理演变轨迹",
    "logic_hooks": {{
        "callback": "回收的前文伏笔",
        "setup": "为后文埋下的新矛盾"
    }},
    "estimated_word_count": {word_target}
}}
"""


CHAPTER_OUTLINE_SCHEMA = {
    "chapter_number": "integer",
    "title": "string",
    "word_count_distribution": "string",
    "scenes": "array",
    "internal_monologue": "string",
    "logic_hooks": "object",
    "estimated_word_count": "integer",
}
