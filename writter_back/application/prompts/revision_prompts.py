"""修正提示词"""

import json


def build_user_instruction_revision_prompt(
    instructions: str,
    current_content: str,
    chapter_outline: dict,
) -> str:
    """用户指令修正的提示词 — 定向优化 + 全文同步"""
    return f"""
请根据【用户修正指令】，对当前章节进行定向优化。

【指令理解】
用户指令为："{instructions}"
请将该指令转化为具体的：性格表现、对话基调、以及情节张力的变化。

【原章节背景】
标题：{chapter_outline.get('title', '')}
章节细纲（必须遵循）：
{json.dumps(chapter_outline, ensure_ascii=False)}
正文：
{current_content}

【修正约束】
1. 风格对齐：在执行指令的同时，保持原有的文笔水准和叙事视角。
2. 全文重构：不要只修改某一句，要确保整章中涉及该指令逻辑的部分都得到同步更新
   （例如：如果要求主角变强，其对应的配角反应也需调整）。
3. 字数维护：保持 3000 字以上的内容密度，不允许因修改指令而导致章节篇幅大幅缩减。

请输出修正后的完整章节：
"""


def build_auto_fix_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_outline: dict,
) -> str:
    """AI自动修正的提示词 — 深度重构 + 逻辑缝合"""
    return f"""
你现在是一名精益求精的资深编辑。请针对提供的【问题列表】，对章节内容进行深度重构修正。

【核心修正原则】
1. 精准手术：针对问题列表中提到的具体段落进行"手术级"修改，严禁删除未受影响的剧情细节。
2. 逻辑缝合：修正后的情节必须与《章节细纲》保持高度一致，并确保与前文逻辑自洽。
3. 质量保底：修正后的内容严禁缩水。若原内容因注水被批评，请用更有张力的心理描写或环境细节替换，而非简单删除。

【待修正资料】
问题列表：
{issues_text}

原章节内容：
{current_content}

必须遵循的章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

【输出要求】
- 直接输出修正后的全文。
- 确保字数维持在 3000-7000 字之间。
- 在修正处通过更细腻的动作和环境描写来增强代入感。
"""


def format_issues_for_prompt(issues: list) -> str:
    """将问题列表格式化为提示词文本，High 严重度加视觉标记"""
    lines = []
    for issue in issues:
        severity = issue.get("severity", "low")
        prefix = "！！！必须优先解决 " if severity == "high" else ""
        lines.append(
            f"- [{issue.get('type', 'unknown')}]({severity}) "
            f"{prefix}"
            f"{issue.get('location', '')}: "
            f"{issue.get('description', '')} "
            f"(建议: {issue.get('suggestion', '')})"
        )
    return "\n".join(lines)


def build_revision_system_prompt() -> str:
    """修正的系统提示词"""
    return """你是一位顶级网络小说主编。
你的任务是根据反馈意见改进稿件。你不仅擅长修补逻辑漏洞（Plot Holes），更擅长通过增加感官细节、心理博弈和潜台词来提升正文的质感。
在修正过程中，你必须平衡"逻辑准确性"与"文学感染力"，并严格遵守字数下限约束。"""


def build_expansion_prompt(
    current_content: str,
    chapter_outline: dict,
    target_words: int,
) -> str:
    """字数不足时的扩写提示词 — 感官填充 + 逻辑缝合"""
    return f"""
你现在是一名精益求精的资深编辑。以下章节在修正后字数严重缩水，请对其进行深度扩写。

【扩写原则】
1. 品质填充：不得添加无意义的废话或重复描述。每一处扩写必须服务于：人物塑造、情节推进、或氛围营造。
2. 逻辑缝合：扩写内容必须与《章节细纲》保持一致，不能偏离原有情节走向。
3. 修正保留：已经完成的修正成果（逻辑修复、OOC修正等）必须完整保留，不得回退。

【扩写技巧指南】（请选择至少 2-3 项应用）
- 感官扩容：为关键场景补充嗅觉、触觉、温度感（如「空气中有铁锈味」「指尖传来粗糙的触感」）
- 心理纵深：在冲突节点插入角色的内心博弈、矛盾权衡、或瞬间回忆（闪回不超过 30 字）
- 环境映射：让环境描写反映人物情绪（焦虑→闷热压抑；决断→冷风骤起）
- 对话潜台词：给简短对话添加动作衬词或语气停顿（如「他沉默了三秒才开口」）
- 慢镜头拆解：将关键动作拆解为 2-3 个连续动态过程

【扩写资料】
当前内容（需要扩写的正文）：
{current_content}

章节细纲（必须遵循）：
{json.dumps(chapter_outline, ensure_ascii=False)}

【输出要求】
- 直接输出扩写后的完整正文，不要加任何说明。
- 目标字数：{target_words} 字左右。
- 确保扩写部分与原文无缝融合，不出现生硬插入的痕迹。
"""


REVISION_TEMPERATURE = 0.5
