"""章节细纲生成提示词（深度优化版）

优化维度：
1. 场景三阶段化（Tri-Phase Scenes）：入场-拉锯-结果
2. 感官结构细化（Sensory Details）：视觉/听觉/嗅觉触觉
3. 对话明暗线拆解（Dialogue Mapping）：明线/暗线潜台词
4. 逻辑钩子具体化（Logic Hooks）：指定影响的具体章节
"""

import random


def build_chapter_outline_prompt(
    chapter_index: int,
    novel_type: str,
    title: str,
    chapter_theme: str,
    key_events: list,
    memory_context: str,
) -> str:
    """生成深度章节细纲的提示词"""
    theme_str = chapter_theme or '未指定'
    events_str = str(key_events) if key_events else "[]"
    ctx = memory_context[:1200] if memory_context else "无"
    word_target = random.randint(3500, 5500)

    return f"""请为第 {chapter_index} 章生成深度细纲。本细纲必须具备极高的内容密度，足以支撑 3000-7000 字的正文创作。

【本章上下文】
书名/类型：{title} / {novel_type}
本章主题/事件：{theme_str} | {events_str}
前文提要：{ctx}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心生成约束——必须逐条遵守】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① 场景三阶段化（Tri-Phase Scenes）
本章必须拆解为 3-5 个具体场景。每个场景的 events 必须按「入场—拉锯—结果」三阶段组织：
- 入场（Entry）：环境描写 + 角色登场 + 初始氛围渲染
- 拉锯（Struggle）：心理博弈 + 冲突升级 + 信息交锋
- 结果（Result）：关系位移 + 场景落点 + 情感余波

即使是一个简单的谈话场景，也要包含环境渲染（入场）、心理博弈（拉锯）和关系变化（结果）。

② 感官三位一体（Sensory Trinity）
每个场景的 sensory_details 必须包含三类感官（非视觉不可缺）：
- visual：视觉描写（光影/色彩/人物神态/环境布局）
- auditory：听觉描写（环境音/对话语气/停顿与沉默/脚步声等）
- olfactory_tactile：嗅觉/触觉（气味/温度/纹理/触感/空气湿度等）
❌ 禁止只写视觉。三种感官齐备才能让正文有沉浸感。

③ 对话明暗线拆解（Dialogue Mapping）
每个场景的 dialogue_targets 必须拆分为明线和暗线：
- explicit（明线）：表面要达成的对话目标（如：说服对方交出钥匙）
- implicit（暗线/潜台词）：角色真正想表达的或隐藏的信息（如：其实在试探对方是否可信）
❌ 禁止只写直线条的目的。"高级感"来自明暗线之间的张力。

④ 逻辑钩子具体化（Hooks Targeting）
logic_hooks 必须指定对后文具体哪一章的影响：
- callback：回收前文哪一章的伏笔 + 具体是什么
- setup：为后文具体哪一章埋下新矛盾 + 矛盾的具体描述
❌ 禁止写"为后文埋下伏笔"这种模糊表述，必须指定章节号和具体内容。

⑤ 字数分配清晰化
word_count_distribution 必须按场景阶段给出具体字数，而非笼统配比。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【输出 JSON 格式】
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
    "chapter_number": {chapter_index},
    "title": "富有感染力的章节标题",
    "word_count_distribution": "场景1入场(400字)/拉锯(700字)/结果(400字), 场景2入场(300字)...",
    "scenes": [
        {{
            "location": "场景地点",
            "characters": ["涉及人物及当前情感状态"],
            "events": {{
                "entry": "入场：环境描写与角色登场",
                "struggle": "拉锯：心理博弈与冲突升级",
                "result": "结果：关系位移与场景落点"
            }},
            "sensory_details": {{
                "visual": "视觉描写（光影/色彩/人物神态）",
                "auditory": "听觉描写（环境音/语气/停顿）",
                "olfactory_tactile": "嗅觉/触觉描写（气味/温度/质感）"
            }},
            "dialogue_targets": {{
                "explicit": "明线：表面要达成的对话目标",
                "implicit": "暗线/潜台词：角色真正想说的或隐藏的信息"
            }},
            "purpose": "该场景在全书逻辑中的必要性"
        }}
    ],
    "internal_monologue": "主角在本章的核心心理演变轨迹",
    "logic_hooks": {{
        "callback": "回收前文第X章的伏笔：具体伏笔内容",
        "setup": "为后文第Y章埋下新矛盾：具体矛盾描述"
    }},
    "estimated_word_count": {word_target}
}}

确保 JSON 格式正确，所有字段完整。遇到对话场景务必填写 dialogue_targets。"""


CHAPTER_OUTLINE_SCHEMA = {
    "chapter_number": "integer",
    "title": "string",
    "word_count_distribution": "string",
    "scenes": "array",          # scenes[].events -> dict, scenes[].sensory_details -> dict, scenes[].dialogue_targets -> dict
    "internal_monologue": "string",
    "logic_hooks": "object",    # callback/setup now include target chapter
    "estimated_word_count": "integer",
}
