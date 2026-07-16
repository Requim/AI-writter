"""反思检查提示词"""

import json

from application.continuity import build_budgeted_context, compact_text


CHUNK_SIZE = 2000
CHUNK_OVERLAP = 200


def split_into_chunks(
    text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP
) -> list[dict]:
    """将文本按固定大小分块，带重叠区域

    Returns:
        [{"start": 0, "end": 2000, "text": "..."}, ...]
    """
    if len(text) <= chunk_size:
        return [{"start": 0, "end": len(text), "text": text, "chunk_index": 0}]
    chunks = []
    pos = 0
    idx = 0
    while pos < len(text):
        end = min(pos + chunk_size, len(text))
        chunk_text = text[pos:end]
        chunks.append(
            {"start": pos, "end": end, "text": chunk_text, "chunk_index": idx}
        )
        idx += 1
        pos += chunk_size - overlap
        if pos >= len(text):
            break
    return chunks


def build_chunk_reflection_prompt(
    chunk_text: str,
    chunk_index: int,
    total_chunks: int,
    chunk_start: int,
    chunk_end: int,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    story_bible: str = "",
) -> str:
    """分块检查提示词 — 只检查该块内的局部问题"""
    return f"""
你正在检查小说章节的第 {chunk_index + 1}/{total_chunks} 块（字符位置 {chunk_start}-{chunk_end}）。
请只针对你看到的这段内容进行局部审核。

【审核范围（仅限本块）】
1. 人物一致性（OOC）：本块中的角色行为是否符合其性格设定？
2. 信息密度：本块是否存在注水/废话段落？
3. 叙事节奏：本块的节奏是否合理（过慢或过快）？
4. 局部逻辑：本块内部是否有前后矛盾之处？

【严重等级定义】
- low（轻微）：笔误、标点错误、文风微调
- medium（一般）：场景不够饱满、节奏略慢
- high（严重）：人设崩塌（OOC）、逻辑硬伤、注水严重

【修改优先级】
- must_fix：必须修改（对应 high severity 问题）
- optional：可酌情处理（对应 medium severity）
- can_ignore：可忽略（对应 low severity）

【输入数据】
待检查段落：
{chunk_text}

章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

总纲领人物志：
{json.dumps(main_characters, ensure_ascii=False)}

前文上下文：
{build_budgeted_context(memory_context, max_chars=1800)}

静态故事圣经：
{compact_text(story_bible, 1400) if story_bible else "无"}

输出JSON格式：
{{{{
    "issues": [
        {{{{
            "type": "consistency|character|padding|pacing|plot_hole",
            "severity": "low|medium|high",
            "priority_action": "must_fix|optional|can_ignore",
            "issue_resolved": false,
            "location": "本块中的具体段落描述",
            "description": "问题的具体描述",
            "evidence": "体现问题的原句（30字内）",
            "suggestion": "修改建议"
        }}}}
    ]
}}}}
"""


def build_aggregation_prompt(
    chunk_results: list[dict],
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
    story_bible: str = "",
) -> str:
    """聚合 prompt — 综合所有分块的局部检查结果 + 做全局检查（逻辑链、伏笔、总体评分）"""
    chunks_summary = ""
    for i, cr in enumerate(chunk_results):
        issues = cr.get("issues", [])
        if issues:
            chunks_summary += f"第{i + 1}块（{cr.get('start', 0)}-{cr.get('end', 0)}字符）发现 {len(issues)} 个问题：\n"
            for iss in issues:
                chunks_summary += f"  - [{iss.get('type', '?')}]({iss.get('severity', '?')}) {iss.get('description', '')}\n"
        else:
            chunks_summary += f"第{i + 1}块：无问题\n"

    return f"""
你现在是一名资深文学编辑，负责对整章内容进行最终审核。
下面是分段检查的结果汇总，请结合这些局部信息和你对全文的理解，做全局判断。

【分段检查结果】
{chunks_summary}

【全局审核（本次重点）】
1. 逻辑闭环：结合所有段落，本章是否有跨段落的力量体系矛盾或逻辑断裂？
2. 衔接压力：本章开头是否承接前文？结尾是否埋下钩子？
3. 细纲覆盖率：所有细纲中的场景是否都已覆盖？
4. 伏笔检查：细纲要求的伏笔是否在本章中被隐晦提及？
5. 综合质量评分 0-1：综合考虑全文质量（不只看局部）。

【输入数据】
完整章节正文（全局审核必须逐段核对，不得只依赖分块结论）：
{compact_text(chapter_content, 9000, tail_ratio=0.45)}

章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

总纲领人物志：
{json.dumps(main_characters, ensure_ascii=False)}

前文上下文：
{build_budgeted_context(memory_context, max_chars=2600)}

静态故事圣经：
{compact_text(story_bible, 2200) if story_bible else "无"}

输出JSON格式：
{{{{
    "passed": true或false,
    "overall_quality_score": "0.0-1.0（0.8以下不通过）",
    "word_count_analysis": {{{{
        "total_count": {content_length},
        "effective_density": "有效内容占比(0-100)",
        "is_valid_word_count": true或false
    }}}},
    "issues": "array（合并所有分块的 issues，加上全局发现的问题）",
    "logic_chain_status": "本章与前文的衔接情况",
    "foreshadowing_check": "伏笔是否已提及"
}}}}
"""


def build_reflection_prompt(
    chapter_content: str,
    chapter_outline: dict,
    main_characters: list,
    memory_context: str,
    content_length: int,
    story_bible: str = "",
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

【修改优先级定义】
对每个 issue，请根据严重等级和问题类型综合判定 priority_action：
- must_fix：必须优先修改，不允许折衷。对应 severity=high 的逻辑/OOC/力量体系/有效密度问题
- optional：次要优化，可酌情处理。对应 severity=medium 的问题
- can_ignore：轻微问题，可忽略。对应 severity=low 的问题

【问题解决状态】
如果是本轮修正后的再次检查，请对比修正后的内容，判断之前的问题是否已解决：
- issue_resolved=true：该问题已在本轮修正中解决
- issue_resolved=false：该问题仍未解决
- suggested_fix_text：针对 must_fix 问题，请提供具体的修改示例或模板，供修正节点直接使用

【输入数据】
章节完整内容：
{compact_text(chapter_content, 9000, tail_ratio=0.45)}

章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

总纲领人物志：
{json.dumps(main_characters, ensure_ascii=False)}

前文上下文（<S层故事状态> | <M层近期章节> | <L层历史章节摘录>）：
{build_budgeted_context(memory_context, max_chars=2600)}

静态故事圣经：
{compact_text(story_bible, 2200) if story_bible else "无"}

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
            "priority_action": "must_fix|optional|can_ignore",
            "issue_resolved": false,
            "suggested_fix_text": "针对 must_fix 问题提供具体修改示例（如：将'xxx'改为'yyy'）",
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


CHUNK_REFLECTION_SCHEMA = {
    "issues": {
        "type": "string",
        "severity": "string",
        "priority_action": "string",
        "issue_resolved": "boolean",
        "location": "string",
        "description": "string",
        "evidence": "string",
        "suggestion": "string",
    },
}

AGGREGATION_SCHEMA = {
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
