"""反思检查提示词"""

import json


def build_reflection_prompt(
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
) -> str:
    """反思检查的提示词（地摊式逻辑审核）"""
    return f"""
你现在是一名资深文学编辑，负责对以下章节内容进行"地毯式"逻辑审核。
请保持极高的批判性，拒绝任何平庸或自相矛盾的内容。

【审核基准】

1. 逻辑闭环（力量体系与规则限制）
   对照总纲领中设定的"力量体系限制"或"社会规则"，检查本章是否存在以下问题：
   - 主角突然获得了总纲里没有的"金手指"或能力
   - 力量体系前后矛盾（如上一章灵力耗尽，这一章却轻易施法）
   - 社会规则/世界观设定被违反

2. 人物一致性（OOC 检测）
   对比《主角信息》，检查角色是否存在"降智"或"人设崩塌"行为：
   - 角色做出了不符合其性格、智商、背景的决策
   - 对话风格与角色设定不匹配

3. 细纲覆盖率
   逐条比对《章节细纲》中的场景目的与感官细节是否全数达成：
   - 细纲中列出的每个场景是否都已写到
   - 细纲要求的伏笔、人物心理变化是否体现

4. 真实信息密度（有效内容占比 Effective Density）
   识别"废话"和"无效描写"（即删掉后不影响剧情推进的内容），包括：
   - 重复的形容词堆砌（如"黑暗的、阴森的、恐怖的"连用）
   - 无信息量的环境描写（超过3句纯景物但无剧情推进）
   - 角色内心独白的无效重复
   - 有效内容占比 = 有效剧情字数 / 总字数 × 100%
   - **如果有效占比低于 70%，即使总字数达标，也要判定为 padding（注水）**
   - 在 issues 中标记出具体的注水段落

5. 衔接压力（前文逻辑链）
   检查本章与前文的连贯性：
   - 本章开头是否承接了《前文上下文》的紧张感（Tension）
   - 如果前文说主角重伤/灵力耗尽，这一章生龙活虎 → 必须识别为 high severity 逻辑错误
   - 结尾是否成功埋下钩子，为下一章制造悬念

【严重等级定义】
- low（轻微）：笔误、标点错误、文风微调
- medium（一般）：细纲中某个小点漏掉了、某个场景不够饱满
- high（严重）：人设崩塌（OOC）、逻辑硬伤、力量体系崩坏、字数严重不足（<2500）、有效密度低于 70%

【输入数据】
章节内容（前2500字摘要）：
{chapter_content[:2500]}...

章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

总纲领人物志：
{json.dumps(main_characters, ensure_ascii=False)}

前文上下文（摘要）：
{memory_context[:800] if memory_context else '无'}

输出JSON格式：
{{
    "passed": true或false,
    "overall_quality_score": 0.0-1.0之间的数字（0.8以下建议重写）,
    "word_count_analysis": {{
        "total_count": {content_length},
        "effective_density": "有效内容占比(0-100的整数)",
        "is_valid_word_count": true或false
    }},
    "issues": [
        {{
            "type": "logic|consistency|plot_hole|character|padding|pacing|power_system|tension_gap",
            "severity": "low|medium|high",
            "location": "具体情节或对话段落",
            "description": "请指出具体哪里不符合逻辑或哪里在注水",
            "evidence": "原文中体现该问题的具体短句（50字内）",
            "suggestion": "如何修改能让冲突更激烈或逻辑更严密"
        }}
    ],
    "logic_chain_status": "描述本章与前文的衔接是否存在断层",
    "foreshadowing_check": "细纲要求的伏笔是否已在文中隐晦提及？如未提及请说明"
}}
"""


REFLECTION_SCHEMA = {
    "passed": "boolean",
    "overall_quality_score": "number",
    "word_count_analysis": {
        "total_count": "integer",
        "effective_density": "number",
        "is_valid_word_count": "boolean",
    },
    "issues": "array",
    "logic_chain_status": "string",
    "foreshadowing_check": "string",
}
