"""修正提示词"""

import json

from application.continuity import build_budgeted_context, compact_text


def _continuity_block(continuity_context: str, story_bible: str) -> str:
    return f"""
【连续性硬约束】
静态故事圣经：
{compact_text(story_bible, 2400) if story_bible else "无"}

前文累计状态与滚动规划：
{build_budgeted_context(continuity_context, max_chars=3200)}

修订不得改变未被问题列表点名的既有事实、人物知识边界、时间线和伏笔状态。
"""


def build_user_instruction_revision_prompt(
    instructions: str,
    current_content: str,
    chapter_outline: dict,
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """用户指令修正的提示词 — 定向优化 + 全文同步"""
    return f"""
请根据【用户修正指令】，对当前章节进行定向优化。

【指令理解】
用户指令为："{instructions}"
请将该指令转化为具体的：性格表现、对话基调、以及情节张力的变化。

【原章节背景】
标题：{chapter_outline.get("title", "")}
章节细纲（必须遵循）：
{json.dumps(chapter_outline, ensure_ascii=False)}
正文：
{current_content}

{_continuity_block(continuity_context, story_bible)}

【修正约束】
1. 风格对齐：在执行指令的同时，保持原有的文笔水准和叙事视角。
2. 全文重构：不要只修改某一句，要确保整章中涉及该指令逻辑的部分都得到同步更新
   （例如：如果要求主角变强，其对应的配角反应也需调整）。
3. 字数维护：保持 3000 字以上的内容密度，不允许因修改指令而导致章节篇幅大幅缩减。

请输出修正后的完整章节：
"""


# ============================================================
# 修正模式定义
# ============================================================
# Patch 模式触发条件（小问题，局部修改）
PATCH_TRIGGER_TYPES = {
    "consistency",
    "character",
    "padding",
    "pacing",
    "tension_gap",
    "plot_hole",
}
# Refactor 模式触发条件（严重问题，需要全文重构）
REFACTOR_TRIGGER_TYPES = {
    "power_system",
    "logic",
}


def classify_revision_mode(issues: list) -> str:
    """根据问题列表判断修正模式：patch（局部修正）或 refactor（全文重构）

    判定规则：
    - 如果存在 type=power_system 或 type=logic 的 must_fix 问题 → refactor
    - 如果 effective_density < 50% 或大规模 OOC → refactor
    - 其他情况 → patch
    """
    for issue in issues:
        itype = issue.get("type", "")
        pa = issue.get("priority_action", "optional")
        if pa == "must_fix":
            if itype in REFACTOR_TRIGGER_TYPES:
                return "refactor"
    return "patch"


def build_patch_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_outline: dict,
    revision_history: str = "",
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """Patch 模式修正提示词 — 局部修改 + 严格范围限制"""
    history_block = (
        f"\n【此前修改记录】\n{revision_history}\n请避免重复修改已解决的问题，也不要回退之前的修正成果。"
        if revision_history
        else ""
    )

    return f"""
你现在是一名精益求精的资深编辑。请针对提供的【问题列表】，对章节内容进行精准局部修正。

【核心修正原则】
1. 精准定位：只修改 issue 提及的具体段落。禁止改写未涉及的内容。
2. 修改范围限制：除 issue 涉及内容外：
   - 禁止改写已有剧情
   - 禁止新增支线
   - 禁止修改角色核心性格
   - 禁止改变章节节奏结构
3. 局部操作：只允许修改 issue 涉及段落前后 300 字范围内的内容，禁止重写整章。
4. 类型驱动修正：每种问题类型对应不同的修改策略：
   - type=consistency / character → 修改角色行为或心理描写，保证人设前后一致
   - type=padding → 替换注水内容为有效情节，而非简单删除
   - type=pacing / tension_gap → 调整段落节奏
   - type=plot_hole → 修补逻辑漏洞
5. 优先级顺序：严格按照 priority_action 依次处理：must_fix → optional → can_ignore{history_block}

【待修正资料】
问题列表：
{issues_text}

原章节内容：
{current_content}

必须遵循的章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

{_continuity_block(continuity_context, story_bible)}

【输出要求】
- 直接输出修正后的全文（未修改部分原文保留）。
- 只改问题段落及其前后衔接，其他内容一字不动。
- 不用写任何说明或标记。
"""


def build_refactor_revision_prompt(
    issues_text: str,
    current_content: str,
    chapter_outline: dict,
    revision_history: str = "",
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """Refactor 模式修正提示词 — 全文重构 + 逻辑缝合"""
    history_block = (
        f"\n【此前修改记录】\n{revision_history}\n请避免重复修改已解决的问题，也不要回退之前的修正成果。"
        if revision_history
        else ""
    )

    return f"""
你现在是一名顶级小说主编。本章存在严重的结构性问题（力量体系崩坏/主线逻辑断裂/大规模 OOC），需要进行全文重构。

【核心修正原则】
1. 必须优先解决 priority_action=must_fix 的全部问题，不允许折衷。
2. 类型驱动修正：
   - type=logic / power_system → 调整事件顺序、因果链、力量体系一致性
   - type=consistency / character / plot_hole → 修改角色行为或心理描写，保证人设前后一致
   - type=padding → 用有效情节替换注水内容
   - type=pacing / tension_gap → 调整叙事节奏
3. 全文重构：涉及逻辑骨架的问题可能波及多个段落，允许跨段落重写，但必须保留原有剧情走向和角色核心性格。
4. 逻辑缝合：修正后的内容必须与《章节细纲》保持一致，并确保与前文逻辑自洽。
5. 质量保底：修正后的内容严禁缩水，用更有张力的描写替换注水内容。{history_block}

【待修正资料】
问题列表：
{issues_text}

原章节内容：
{current_content}

必须遵循的章节细纲：
{json.dumps(chapter_outline, ensure_ascii=False)}

{_continuity_block(continuity_context, story_bible)}

【输出要求】
- 直接输出修正后的全文。
- 确保字数维持在 3000-7000 字之间。
- 不得输出修改说明、批注或“已修正”标记。
"""


def format_issues_for_prompt(issues: list) -> str:
    """将问题列表格式化为提示词文本，含优先级标记和修改建议"""
    lines = []
    for issue in issues:
        priority = issue.get("priority_action", "optional")
        severity = issue.get("severity", "low")
        pa_tag = {
            "must_fix": "【必须修正】",
            "optional": "【次要】",
            "can_ignore": "【可忽略】",
        }
        tag = pa_tag.get(priority, "【次要】")
        fix_text = issue.get("suggested_fix_text", "")
        fix_block = f"\n    修改示例: {fix_text}" if fix_text else ""
        lines.append(
            f"- {tag}[{issue.get('type', 'unknown')}]({severity}) "
            f"{issue.get('location', '')}: "
            f"{issue.get('description', '')} "
            f"(建议: {issue.get('suggestion', '')}){fix_block}"
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
    continuity_context: str = "",
    story_bible: str = "",
) -> str:
    """字数不足时的扩写提示词 — 感官填充 + 逻辑缝合"""
    return f"""
你现在是一名精益求精的资深编辑。以下章节在修正后字数严重缩水，请对其进行深度扩写。

【扩写原则】
1. 品质填充：不得添加无意义的废话或重复描述。每一处扩写必须服务于：人物塑造、情节推进、或氛围营造。
2. 逻辑缝合：扩写内容必须与《章节细纲》保持一致，不能偏离原有情节走向。
3. 修正保留：已经完成的修正成果（逻辑修复、OOC修正等）必须完整保留，不得回退。
4. 有效填充：扩写内容必须推进情节或塑造人物。禁止添加以下类型的内容：
   - 与主线无关的景物堆砌（超过 2 句纯景物描写必须映射人物心理）
   - 角色内心独白的无效重复（相同情绪不重复描写超过一次）
   - 已完成修正的逻辑修改不能被新扩写内容覆盖或回退

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

{_continuity_block(continuity_context, story_bible)}

【输出要求】
- 直接输出扩写后的完整正文，不要加任何说明。
- 目标字数：{target_words} 字左右。
- 确保扩写部分与原文无缝融合，不出现生硬插入的痕迹。
"""


# 修正温度：Patch 模式低温度（保守），Refactor 模式中温度（创造性）
PATCH_TEMPERATURE = 0.3
REFACTOR_TEMPERATURE = 0.55
# 兼容旧引用
REVISION_TEMPERATURE = 0.5
