"""章节写作提示词（兼容新旧细纲格式 + 场景队列生成）

优化点：
1. 解决"中途乏力"：信息密度 + 段落权重 + 均匀分布
2. 强化"逻辑钩子"强制执行：前10%回收Callback，后10%埋设Setup
3. 提升对话"非直接性"：动作辅助对话，禁止连续纯对白
4. 场景队列生成：逐个场景生成（用于 node 侧调度）
"""

import json

from application.continuity import build_budgeted_context, compact_text
from application.prompts.version import PROMPT_VERSION
from application.word_budget import chapter_target_words


def _fmt_events(events) -> str:
    """兼容 events: array（旧）或 dict（新"""
    if isinstance(events, dict):
        parts = []
        if events.get("entry"):
            parts.append(f"  【入场】{events['entry']}")
        if events.get("struggle"):
            parts.append(f"  【拉锯】{events['struggle']}")
        if events.get("result"):
            parts.append(f"  【结果】{events['result']}")
        return "\n".join(parts) if parts else "未指定"
    if isinstance(events, list):
        return "\n    ".join(events) or "未指定"
    return str(events) or "未指定"


def _fmt_sensory(sensory) -> str:
    """兼容 sensory_details: array（旧）或 dict（新）"""
    if isinstance(sensory, dict):
        parts = []
        if sensory.get("visual"):
            parts.append(f"  [视觉] {sensory['visual']}")
        if sensory.get("auditory"):
            parts.append(f"  [听觉] {sensory['auditory']}")
        if sensory.get("olfactory_tactile"):
            parts.append(f"  [嗅觉/触觉] {sensory['olfactory_tactile']}")
        return "\n".join(parts) if parts else "无"
    if isinstance(sensory, list):
        return "\n    ".join(sensory) or "无"
    return str(sensory) or "无"


def _fmt_dialogue(dialogue) -> str:
    """兼容 dialogue_targets: array（旧）或 dict（新）"""
    if isinstance(dialogue, dict):
        parts = []
        if dialogue.get("explicit"):
            parts.append(f"  [明线] {dialogue['explicit']}")
        if dialogue.get("implicit"):
            parts.append(f"  [暗线/潜台词] {dialogue['implicit']}")
        return "\n".join(parts) if parts else "无"
    if isinstance(dialogue, list):
        return "\n    ".join(dialogue) or "无"
    return str(dialogue) or "无"


def _build_scene_block(scene_num: int, scene: dict) -> str:
    """构建单个场景的描述块"""
    loc = scene.get("location", "未指定")
    chars = "、".join(scene.get("characters", [])) or "未指定"
    events = _fmt_events(scene.get("events"))
    sensory = _fmt_sensory(scene.get("sensory_details"))
    dialogue = _fmt_dialogue(scene.get("dialogue_targets"))
    purpose = scene.get("purpose", "未指定")
    dramatic = {
        "scene_goal": scene.get("scene_goal", ""),
        "desire": scene.get("desire", ""),
        "obstacle": scene.get("obstacle", ""),
        "tactic": scene.get("tactic", ""),
        "turn": scene.get("turn", ""),
        "price_paid": scene.get("price_paid", ""),
        "state_delta": scene.get("state_delta", ""),
        "exit_hook": scene.get("exit_hook", ""),
    }
    return (
        f"  【场景{scene_num}】{loc}\n"
        f"    人物与状态：{chars}\n"
        f"    情节阶段：\n{events}\n"
        f"    感官素材：\n{sensory}\n"
        f"    对话设计：\n{dialogue}\n"
        f"    戏剧动作：{json.dumps(dramatic, ensure_ascii=False)}\n"
        f"    场景必要性：{purpose}"
    )


def _build_contract_block(chapter_outline: dict) -> str:
    """Format the continuity-critical subset of the chapter contract."""
    contract = {
        "chapter_goal": chapter_outline.get("chapter_goal", ""),
        "pov_character": chapter_outline.get("pov_character", ""),
        "dramatic_question": chapter_outline.get("dramatic_question", ""),
        "desire": chapter_outline.get("desire", ""),
        "obstacle": chapter_outline.get("obstacle", ""),
        "tactics": chapter_outline.get("tactics", []),
        "turn": chapter_outline.get("turn", ""),
        "price_paid": chapter_outline.get("price_paid", ""),
        "state_delta": chapter_outline.get("state_delta", ""),
        "ending_mode": chapter_outline.get("ending_mode", ""),
        "entry_state": chapter_outline.get("entry_state", {}),
        "causal_chain": chapter_outline.get("causal_chain", []),
        "state_changes": chapter_outline.get("state_changes", []),
        "knowledge_boundaries": chapter_outline.get("knowledge_boundaries", []),
        "continuity_constraints": chapter_outline.get("continuity_constraints", []),
        "exit_state": chapter_outline.get("exit_state", {}),
    }
    return json.dumps(contract, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────
#  写作指令常量（所有场景生成共用）
# ─────────────────────────────────────────────

_WRITING_INSTRUCTIONS = """
【小说化执行原则】
1. 先让 POV 人物为 desire 采取具体行动，再让 obstacle 主动反制；人物必须因受阻而改变 tactic。
2. turn 必须由已发生的行动、误判或选择引起；price_paid 与 state_delta 要在正文中有可引用证据。
3. 严守 POV 知识边界。叙述只能呈现视角人物能感知、回忆或合理推断的信息。
4. 对话是否直白、动作是否穿插、描写快慢由场景目的决定。需要博弈时写潜台词，
   需要决断时允许短而直接；禁止为了满足固定比例重复动作、生理反应或环境意象。
5. 选择少量具体且有辨识度的细节，让细节参与冲突或暴露人物，不堆叠感官清单。
6. 保持人物各自的词汇、句长、回避方式和情绪防御，不使用可互换的通用台词。
7. 场景结束时完成自己的 state_delta，并把其后果交给下一场景；不得重述上一场景已确认的信息。
8. 结尾服从 ending_mode 和本章行动后果。悬念、留白或收束按故事需要选择，不强制惊吓式断章。
"""

_SYSTEM_PROMPT_EXTRA = (
    "你同时也是一位电影导演，懂得用场景思维组织叙事——"
    "每个场景有自己的起承转合，场景之间通过情绪和逻辑衔接。"
    "你的文字没有废笔，每一段描写都服务于人物心理或情节推进。"
)


# ─────────────────────────────────────────────
#  场景队列生成：逐个场景生成
# ─────────────────────────────────────────────

_FIRST_SCENE_TEMPLATE = """请根据以下细纲，撰写第{chapter_num}章的第一个场景（共{total_scenes}个场景）。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
本章场景数：{total_scenes}  当前场景：场景1（共{total_scenes}个）
本场景目标字数：{target_words}字

【本场景细纲】
{scene_block}

【静态故事圣经（不可违背）】
{story_bible}

【本章状态契约】
{contract}

【本章主角心理轨迹】
{internal_monologue}

【本章伏笔与悬念】
- 需自然回收的伏笔（Callback）：{callback}
- 由行动后果埋设的新矛盾（Setup）：{setup}

【前文衔接】
（前文记忆分层：<S层故事状态> | <M层近期章节> | <L层历史章节摘录>）
{context}{previous_tail}

【场景定位】
- 这是本章的「开篇场景」，承担着承接前文、建立本章基调的任务。
- 如果 callback 与本场景因果相关，请在行动中自然回收；否则保留给更合适的场景。
- 场景结尾须自然留出向下一场景过渡的空间。

{instructions}

【输出要求】
- 直接输出正文，不要写"场景1"等标签。
- 本场景目标字数约 {target_words} 字。
- 字数可上下浮动，但不超过目标字数的 120%；优先完成行动与后果，不得用重复描写补足篇幅。
"""


def build_first_scene_prompt(
    scene: dict,
    chapter_outline: dict,
    novel_type: str,
    title: str,
    chapter_num: int,
    ch_title: str,
    memory_context: str,
    target_words: int,
    total_scenes: int,
    logic_hooks: dict,
    internal_monologue: str,
    prev_chapter_tail: str = "",
    story_bible: str = "",
) -> str:
    """生成章节第一个场景的提示词——全量上下文"""
    scene_block = _build_scene_block(1, scene)
    ctx = build_budgeted_context(memory_context, max_chars=3800)
    contract = _build_contract_block(chapter_outline)
    callback_str = logic_hooks.get("callback", "无")
    setup_str = logic_hooks.get("setup", "无")
    prev_tail_block = (
        f"\n【上一章结尾（衔接参考）】\n{prev_chapter_tail}"
        if prev_chapter_tail
        else ""
    )

    return _FIRST_SCENE_TEMPLATE.format(
        chapter_num=chapter_num,
        total_scenes=total_scenes,
        novel_type=novel_type,
        title=title,
        ch_title=ch_title,
        target_words=target_words,
        scene_block=scene_block,
        story_bible=compact_text(story_bible, 2600) if story_bible else "无",
        contract=contract,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=callback_str,
        setup=setup_str,
        context=ctx,
        previous_tail=prev_tail_block,
        instructions=_WRITING_INSTRUCTIONS,
    )


_NEXT_SCENE_TEMPLATE = """请接续上文，撰写第{chapter_num}章的下一个场景（场景{scene_index}/{total_scenes}）。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
当前场景：场景{scene_index}（共{total_scenes}个）
本场景目标字数：{target_words}字

↑ 上一场景核心脉要（Events.Result + 落点氛围）↓
{previous_digest}

【已完成场景账本（均为正文已落地事实）】
{ledger}

【静态故事圣经（不可违背）】
{story_bible}

【本章状态契约与剩余义务】
{contract}

【本场景细纲】
{scene_block}

【本章主角心理轨迹】
{internal_monologue}

【本章伏笔与悬念】
- 需回收的伏笔（Callback）：{callback}
- 待埋设的新矛盾（Setup）：{setup}
- 根据场景账本判断尚未履行的 turn、price_paid 和 state_delta，不得重复已完成事件。

【前文衔接】
（前文记忆分层：<S层故事状态> | <M层近期章节> | <L层历史章节摘录>）
{context}
{correction}

【输出要求】
- 直接输出正文，不要写"场景{scene_index}"等标签。
- 本场景目标字数约 {target_words} 字。
- 注意与上一场景的自然衔接，避免情节跳跃。
- 字数可上下浮动，但不超过目标字数的 120%；不得重复上一场景已经确认的信息。
"""


def build_next_scene_prompt(
    scene: dict,
    chapter_outline: dict,
    novel_type: str,
    title: str,
    chapter_num: int,
    ch_title: str,
    scene_index: int,
    total_scenes: int,
    prev_scene_digest: str,  # 上一场景的 events.result + 结尾氛围
    prev_word_count: int,
    correction_note: str,  # 动态校准提示（字数补偿或精炼要求）
    target_words: int,
    logic_hooks: dict,
    internal_monologue: str,
    memory_context: str,
    story_bible: str = "",
    scene_ledger: list[dict] | None = None,
) -> str:
    """生成后续场景的提示词（带前文摘要和动态校准）"""
    scene_block = _build_scene_block(scene_index, scene)
    ctx = build_budgeted_context(memory_context, max_chars=3200)
    contract = _build_contract_block(chapter_outline)
    callback_str = logic_hooks.get("callback", "无")
    setup_str = logic_hooks.get("setup", "无")
    correction = f"\n【动态校准】{correction_note}" if correction_note else ""
    ledger = compact_text(json.dumps(scene_ledger or [], ensure_ascii=False, indent=2), 2400)

    return _NEXT_SCENE_TEMPLATE.format(
        chapter_num=chapter_num,
        scene_index=scene_index,
        total_scenes=total_scenes,
        novel_type=novel_type,
        title=title,
        ch_title=ch_title,
        target_words=target_words,
        previous_digest=prev_scene_digest,
        ledger=ledger or "无",
        story_bible=compact_text(story_bible, 2200) if story_bible else "无",
        contract=contract,
        scene_block=scene_block,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=callback_str,
        setup=setup_str,
        context=ctx,
        correction=correction,
    )


# ─────────────────────────────────────────────
#  场景续写（当单场景字数不足时）
# ─────────────────────────────────────────────


def build_scene_continue_prompt(
    word_count: int,
    target_words: int,
    existing_content: str,
    correction_note: str = "",
) -> str:
    """场景字数不足时扩展内容的提示词（动态校准版）"""
    base = (
        f"当前场景内容字数 {word_count}，目标 {target_words} 字，字数不足。\n"
        f"请继续扩展本场景内容。优先补充：\n"
        f"1. 只补全尚未完成的行动、反制、信息增量与不可逆代价\n"
        f"2. 不增加纯环境描写、重复情绪、闲聊或规则复述来凑字数\n"
        f"3. 让新增段落改变人物策略、关系或局势\n"
        f"4. 保证新增内容与既有结尾自然衔接\n\n"
        f"已有内容（结尾部分）：\n{existing_content[-800:]}"
    )
    if correction_note:
        base = f"{correction_note}\n\n" + base
    return base


# ─────────────────────────────────────────────
#  保守模式（单次生成整章，用于降级)
# ─────────────────────────────────────────────

_CHAPTER_TEMPLATE = """请根据以下深度细纲，撰写第{chapter_number}章正文内容。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{chapter_title}
字数分配参考：{word_distribution}
本章目标字数：约 {target_words} 字；不得超过目标的 115%，禁止注水。

【细纲数据】
{scenes}

【静态故事圣经（不可违背）】
{story_bible}

【本章状态契约】
{contract}

【主角心理轨迹】
{internal_monologue}

【伏笔与悬念】
- 本章需自然回收的伏笔（Callback）：{callback}
- 由本章行动后果埋下的新矛盾（Setup）：{setup}

【前文衔接】
（前文记忆分层：<S层故事状态> | <M层近期章节> | <L层历史章节摘录>）
{context}{previous_tail}

{instructions}

═══════════════════════════════════
【输出要求】
- 直接输出正文，不要写「场景1」「第1步」等标签。
- 字数严格控制在 3000-7000 字之间。
- 结尾必须产生强烈的「必须翻到下一页」的钩子效果。
"""


def build_chapter_writer_prompt(
    chapter_outline: dict,
    novel_type: str,
    title: str,
    memory_context: str,
    prev_chapter_tail: str = "",
    story_bible: str = "",
) -> str:
    """生成章节内容的提示词——保守模式：单次生成整章

    当场景数 < 3 或场景数据异常时降级使用此模式。
    同样包含全部新约束。
    """
    ch_num = chapter_outline.get("chapter_number", "?")
    ch_title = chapter_outline.get("title", "")
    word_dist = chapter_outline.get("word_count_distribution", "")
    internal_monologue = chapter_outline.get("internal_monologue", "")
    logic_hooks = chapter_outline.get("logic_hooks", {})

    # 构建场景列表（兼容新旧格式）
    scenes = chapter_outline.get("scenes", [])
    scene_blocks = []
    for i, s in enumerate(scenes):
        scene_blocks.append(_build_scene_block(i + 1, s))
    scenes_text = "\n\n".join(scene_blocks)

    ctx = build_budgeted_context(memory_context, max_chars=3800)
    contract = _build_contract_block(chapter_outline)
    prev_tail_block = (
        f"\n【上一章结尾（衔接参考）】\n{prev_chapter_tail}"
        if prev_chapter_tail
        else ""
    )

    return _CHAPTER_TEMPLATE.format(
        chapter_number=ch_num,
        novel_type=novel_type,
        title=title,
        chapter_title=ch_title,
        word_distribution=word_dist or "3000-7000字",
        target_words=chapter_target_words(chapter_outline),
        scenes=scenes_text,
        story_bible=compact_text(story_bible, 2600) if story_bible else "无",
        contract=contract,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=logic_hooks.get("callback", "无"),
        setup=logic_hooks.get("setup", "无"),
        context=ctx,
        previous_tail=prev_tail_block,
        instructions=_WRITING_INSTRUCTIONS,
    )


def build_chapter_continue_prompt(word_count: int, existing_content: str) -> str:
    """字数不足时扩展内容的提示词（降级模式用）"""
    return (
        f"当前章节内容字数 {word_count}，不足 3000 字。\n"
        f"请继续扩展内容。优先补充：\n"
        f"1. 补齐尚未完成的行动、反制、转折与代价\n"
        f"2. 用新信息或人物选择扩展，不重复既有情绪和结论\n"
        f"3. 保持 POV 知识边界与角色声音\n"
        f"4. 让新增内容导向既定 state_delta 和 ending_mode\n\n"
        f"已有内容（结尾部分）：\n{existing_content[-800:]}"
    )


def build_chapter_system_prompt(novel_type: str) -> str:
    """章节写作的系统提示词"""
    return (
        f"[PROMPT_VERSION:{PROMPT_VERSION}]"
        f"你是一位拥有 20 年经验的{novel_type}类型小说家，同时也是一位电影导演。"
        f"你擅用镜头语言写作——知道何时推进、何时慢放、何时留白。"
        f"你的文字没有废笔，每一段描写都服务于人物心理或情节推进。"
    )


CHAPTER_WRITER_TEMPERATURE = 0.78
