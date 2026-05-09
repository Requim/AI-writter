"""章节写作提示词（兼容新旧细纲格式 + 场景队列生成）

优化点：
1. 解决"中途乏力"：信息密度 + 段落权重 + 均匀分布
2. 强化"逻辑钩子"强制执行：前10%回收Callback，后10%埋设Setup
3. 提升对话"非直接性"：动作辅助对话，禁止连续纯对白
4. 场景队列生成：逐个场景生成（用于 node 侧调度）
"""


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
    loc = scene.get('location', '未指定')
    chars = '、'.join(scene.get('characters', [])) or '未指定'
    events = _fmt_events(scene.get('events'))
    sensory = _fmt_sensory(scene.get('sensory_details'))
    dialogue = _fmt_dialogue(scene.get('dialogue_targets'))
    purpose = scene.get('purpose', '未指定')
    return (
        f"  【场景{scene_num}】{loc}\n"
        f"    人物与状态：{chars}\n"
        f"    情节阶段：\n{events}\n"
        f"    感官素材：\n{sensory}\n"
        f"    对话设计：\n{dialogue}\n"
        f"    场景必要性：{purpose}"
    )


# ─────────────────────────────────────────────
#  写作指令常量（所有场景生成共用）
# ─────────────────────────────────────────────

_WRITING_INSTRUCTIONS = """
╔═══════════════════════════════════════════════════════════╗
║            【写作指令——严格遵循以下五点】                    ║
╚═══════════════════════════════════════════════════════════╝

一、信息密度与结构均衡（防"中途乏力"）
  1. 每个场景的字数必须均匀分布。如果本章有3个场景，每个约1500-2000字；
     有4个场景，每个约1000-1500字。严禁场景一洋洋洒洒、场景三草草结束。
  2. 【信息密度原则】正文中不允许出现不推进情节或不传递情感的冗余描写。
     每一段文字必须至少完成以下一项：
     - 提供新信息（线索、反转、背景揭露）
     - 传递情感波动（人物内心变化、关系张力）
     - 推动情节发展（决策、行动、冲突升级）
     ❌ 禁止为凑字数堆砌"无意义但优美的景物描写"——景物必须映射人物心理。
  3. 描写配比参考：动作:对话:心理:环境 ≈ 3:3:2:2

二、逻辑钩子强制执行
  本章的伏笔回收（Callback）和新矛盾埋设（Setup）有严格的段落位置要求：
  1. 【前10%必须体现对 Callback 的回收】
     - 本章开篇就要触及前文伏笔，让读者产生"原来如此"的串联感
     - 可以是一个细节、一句对话、一个物件，但必须明确点出前文的设局
  2. 【后10%必须聚焦于 Setup 的埋设】
     - 本章结尾处要埋下新的矛盾或悬念，确保读者有"必须翻到下一页"的冲动
     - 可以是新的威胁、未解的疑问、人物关系的裂痕
  3. 中间 80% 的内容中，logic_hooks 信息应自然融入情节，不额外强调。

三、对话的非直接性（潜台词 + 动作辅助）
  1. 对话严格遵循"不要直接说出意图"原则——用环境暗示、回避性回答、
     或肢体语言替代直白表达。
  2. 【动作穿插规则】严禁出现连续 3 句以上的纯对白。
     每 2 句对话之间必须穿插一次人物的视觉焦点转移或手部动作描写
     （如："他移开视线，手指在桌面轻轻敲了两下。"）。
  3. 参考细纲中的 dialogue_targets，将"对话目的"转化为"角色真正说出口的话"，
     保留 30% 的潜台词空间。
     - 明线（explicit）：确保表面对话推进情节
     - 暗线（implicit）：通过回避/反问/停顿来制造潜台词张力
  4. 至少 2 处关键对话中，人物的口头表达与内心真实想法相反
     （利用 internal_monologue 制造张力）。

四、镜头感与描写配比
  1. 关键冲突处使用『慢镜头』：将单行动作拆解为连续动态过程
     （如"他拔出枪"→"他的手指触到枪柄冰凉的金属，拇指挑开皮套搭扣，
      虎口卡住握把缓缓收紧……"）。
  2. 每个场景必须包含人物的生理反应描写
     （心跳加速、瞳孔收缩、冷汗、呼吸变浅等），不少于 3 处。
  3. 环境描写须与人物心理形成映射
     （如：焦虑 → 闷热的房间；决断 → 骤起的冷风）。

五、分镜头扩写流程
  请严格按以下步骤逐场景生成内容：
  第1步「细节预演」：利用 sensory_details（视觉/听觉/嗅觉触觉），
    将每个感官素材扩展为 50-100 字的描写段落。
  第2步「情节填充」：按"入场→拉锯→结果"顺序展开 events，
    确保每个阶段有足够的细节支撑，字数分配均匀。
  第3步「对话生成」：根据 dialogue_targets 的明线+暗线设计，
    写出符合人物状态的自然对话，遵守动作穿插规则。
  第4步「转场过渡」：场景之间用 1-2 句环境/心理过渡，保持叙事流畅。
"""

_SYSTEM_PROMPT_EXTRA = (
    "你同时也是一位电影导演，懂得用场景思维组织叙事——"
    "每个场景有自己的起承转合，场景之间通过情绪和逻辑衔接。"
    "你的文字没有废笔，每一段描写都服务于人物心理或情节推进。"
)


# ─────────────────────────────────────────────
#  场景队列生成：逐个场景生成
# ─────────────────────────────────────────────

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
) -> str:
    """生成章节第一个场景的提示词——全量上下文"""
    scene_block = _build_scene_block(1, scene)
    ctx = memory_context[:2000] if memory_context else "无"
    callback_str = logic_hooks.get('callback', '无')
    setup_str = logic_hooks.get('setup', '无')

    return f"""请根据以下细纲，撰写第{chapter_num}章的第一个场景（共{total_scenes}个场景）。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
本章场景数：{total_scenes}  当前场景：场景1（共{total_scenes}个）
本场景目标字数：{target_words}字

【本场景细纲】
{scene_block}

【本章主角心理轨迹】
{internal_monologue or '无特殊要求'}

【本章伏笔与悬念】
- 需回收的伏笔（Callback——须在本章前10%体现）：{callback_str}
- 待埋设的新矛盾（Setup——须在本章后10%聚焦）：{setup_str}

【前文衔接】
{ctx}

【场景定位】
- 这是本章的「开篇场景」，承担着承接前文、建立本章基调的任务。
- 如果 callback 不为空，请在本场景中（或前10%内容中）体现 callback 的回收。
- 场景结尾须自然留出向下一场景过渡的空间。

{_WRITING_INSTRUCTIONS}

【输出要求】
- 直接输出正文，不要写"场景1"等标签。
- 本场景目标字数约 {target_words} 字。
- 字数可上下浮动（若需要更充分展开），但不超过目标字数的 150%。
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
    prev_scene_digest: str,    # 上一场景的 events.result + 结尾氛围
    prev_word_count: int,
    correction_note: str,      # 动态校准提示（字数补偿或精炼要求）
    target_words: int,
    logic_hooks: dict,
    internal_monologue: str,
    memory_context: str,
) -> str:
    """生成后续场景的提示词（带前文摘要和动态校准）"""
    scene_block = _build_scene_block(scene_index, scene)
    ctx = memory_context[:2000] if memory_context else "无"
    callback_str = logic_hooks.get('callback', '无')
    setup_str = logic_hooks.get('setup', '无')
    correction = f"\n【动态校准】{correction_note}" if correction_note else ""

    return f"""请接续上文，撰写第{chapter_num}章的下一个场景（场景{scene_index}/{total_scenes}）。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
当前场景：场景{scene_index}（共{total_scenes}个）
本场景目标字数：{target_words}字

↑ 上一场景核心脉要（Events.Result + 落点氛围）↓
{prev_scene_digest}

【本场景细纲】
{scene_block}

【本章主角心理轨迹】
{internal_monologue or '无特殊要求'}

【本章伏笔与悬念】
- 需回收的伏笔（Callback）：{callback_str}
- 待埋设的新矛盾（Setup——须在本章后10%聚焦）：{setup_str}
- 当前处于本章中部（场景{scene_index}/{total_scenes}），
  情节应逐步推向高潮，为后10%的 Setup 埋设做准备。

【前文衔接】
{ctx}
{correction}

{_WRITING_INSTRUCTIONS}

【输出要求】
- 直接输出正文，不要写"场景{scene_index}"等标签。
- 本场景目标字数约 {target_words} 字。
- 注意与上一场景的自然衔接，避免情节跳跃。
- 字数可上下浮动，但不超过目标字数的 150%。
"""


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
        f"1. 关键冲突处的慢镜头扩写（生理反应 + 环境映射）\n"
        f"2. 对话中的潜台词与动作穿插（每2句对话搭配一次视觉/动作描写）\n"
        f"3. 环境细节与感官描写（视觉/听觉/嗅觉触觉）\n"
        f"4. 人物心理活动的深入刻画\n\n"
        f"已有内容（结尾部分）：\n{existing_content[-800:]}"
    )
    if correction_note:
        base = f"{correction_note}\n\n" + base
    return base


# ─────────────────────────────────────────────
#  保守模式（单次生成整章，用于降级)
# ─────────────────────────────────────────────

def build_chapter_writer_prompt(
    chapter_outline: dict,
    novel_type: str,
    title: str,
    memory_context: str,
) -> str:
    """生成章节内容的提示词——保守模式：单次生成整章

    当场景数 < 3 或场景数据异常时降级使用此模式。
    同样包含全部新约束。
    """
    ch_num = chapter_outline.get('chapter_number', '?')
    ch_title = chapter_outline.get('title', '')
    word_dist = chapter_outline.get('word_count_distribution', '')
    internal_monologue = chapter_outline.get('internal_monologue', '')
    logic_hooks = chapter_outline.get('logic_hooks', {})

    # 构建场景列表（兼容新旧格式）
    scenes = chapter_outline.get("scenes", [])
    scene_blocks = []
    for i, s in enumerate(scenes):
        scene_blocks.append(_build_scene_block(i + 1, s))
    scenes_text = "\n\n".join(scene_blocks)

    ctx = memory_context[:2000] if memory_context else "无"

    return f"""请根据以下深度细纲，撰写第{ch_num}章正文内容。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
    字数分配参考：{word_dist or '3000-7000字'}
    目标字数：不少于3000字，尽量不超过7000字，禁止注水。

【细纲数据】
{scenes_text}

【主角心理轨迹】
{internal_monologue or '无特殊要求'}

【伏笔与悬念】
- 本章需回收的伏笔（Callback——须在前10%体现）：{logic_hooks.get('callback', '无')}
- 为后文埋下的新矛盾（Setup——须在后10%聚焦）：{logic_hooks.get('setup', '无')}

【前文衔接】
{ctx}

{_WRITING_INSTRUCTIONS}

═══════════════════════════════════
【输出要求】
- 直接输出正文，不要写「场景1」「第1步」等标签。
- 字数严格控制在 3000-7000 字之间。
- 结尾必须产生强烈的「必须翻到下一页」的钩子效果。
"""


def build_chapter_continue_prompt(word_count: int, existing_content: str) -> str:
    """字数不足时扩展内容的提示词（降级模式用）"""
    return (
        f"当前章节内容字数 {word_count}，不足 3000 字。\n"
        f"请继续扩展内容。优先补充：\n"
        f"1. 关键冲突处的慢镜头扩写（生理反应 + 环境映射）\n"
        f"2. 对话中的潜台词与动作穿插（每2句对话搭配一次视觉/动作描写）\n"
        f"3. 环境细节与感官描写（视觉/听觉/嗅觉触觉）\n"
        f"4. 场景转场的过渡描写\n\n"
        f"已有内容（结尾部分）：\n{existing_content[-800:]}"
    )


def build_chapter_system_prompt(novel_type: str) -> str:
    """章节写作的系统提示词"""
    return (
        f"你是一位拥有 20 年经验的{novel_type}类型小说家，同时也是一位电影导演。"
        f"你擅用镜头语言写作——知道何时推进、何时慢放、何时留白。"
        f"你的文字没有废笔，每一段描写都服务于人物心理或情节推进。"
    )


CHAPTER_WRITER_TEMPERATURE = 0.85
