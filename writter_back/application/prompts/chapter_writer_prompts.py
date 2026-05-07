"""章节写作提示词"""


def build_chapter_writer_prompt(
    chapter_outline: dict,
    novel_type: str,
    title: str,
    memory_context: str,
) -> str:
    """生成章节内容的提示词——基于深度细纲的镜头式写作"""
    ch_num = chapter_outline.get('chapter_number', '?')
    ch_title = chapter_outline.get('title', '')
    word_dist = chapter_outline.get('word_count_distribution', '')
    internal_monologue = chapter_outline.get('internal_monologue', '')
    logic_hooks = chapter_outline.get('logic_hooks', {})

    # 构建场景列表
    scenes = chapter_outline.get("scenes", [])
    scene_blocks = []
    for i, s in enumerate(scenes):
        loc = s.get('location', '未指定')
        chars = '、'.join(s.get('characters', [])) or '未指定'
        events = '\n    '.join(s.get('events', [])) or '未指定'
        sensory = '\n    '.join(s.get('sensory_details', [])) or '无'
        dialogue = '\n    '.join(s.get('dialogue_targets', [])) or '无'
        purpose = s.get('purpose', '未指定')
        scene_blocks.append(
            f"  【场景{i+1}】{loc}\n"
            f"    人物与状态：{chars}\n"
            f"    情节链：\n    {events}\n"
            f"    感官素材库：\n    {sensory}\n"
            f"    对话目标/金句：\n    {dialogue}\n"
            f"    场景必要性：{purpose}"
        )
    scenes_text = "\n\n".join(scene_blocks)

    ctx = memory_context[:2000] if memory_context else "无"

    return f"""请根据以下深度细纲，撰写第{ch_num}章正文内容。

【基本信息】
小说类型：{novel_type}
书名：{title}
章节标题：{ch_title}
字数分配参考：{word_dist or '3000-6000字'}
目标字数：3000-6000字

【细纲数据】
{scenes_text}

【主角心理轨迹】
{internal_monologue or '无特殊要求'}

【伏笔与悬念】
- 本章需回收的伏笔（Callback）：{logic_hooks.get('callback', '无')}
- 为后文埋下的新矛盾（Setup）：{logic_hooks.get('setup', '无')}

【前文衔接】
{ctx}

═══════════════════════════════════
【写作指令——请严格遵循以下三点】
═══════════════════════════════════

一、镜头感与描写配比
  1. 本章须达到动作:对话:心理:环境 ≈ 3:3:2:2 的描写比例。
  2. 关键冲突处使用『慢镜头』：将单行动作拆解为连续动态过程（如「他拔出枪」→「他的手指触到枪柄冰凉的金属，拇指挑开皮套搭扣，虎口卡住握把缓缓收紧……」）。
  3. 每个场景必须包含人物的生理反应描写（心跳加速、瞳孔收缩、冷汗、呼吸变浅等），不少于 3 处。
  4. 环境描写须与人物心理形成映射（如：焦虑 → 闷热的房间；决断 → 骤起的冷风）。

二、潜台词与留白
  1. 对话严格遵循「不要直接说出意图」原则——用环境暗示、回避性回答、或肢体语言替代直白表达。
  2. 参考细纲中的 dialogue_targets，将「对话目的」转化为「角色真正说出口的话」，保留 30% 的潜台词空间。
  3. 至少 2 处关键对话中，人物的口头表达与内心真实想法相反（利用 internal_monologue 制造张力）。

三、分镜头扩写流程
  请按以下步骤逐场景生成内容：
  第1步「细节预演」：利用 sensory_details 库，将每个感官素材扩展为 50-100 字的描写段落。
  第2步「情节填充」：将 events 中的情节链节点逐一展开，确保逻辑因果清晰。
  第3步「对话生成」：根据 dialogue_targets 写出符合人物状态的自然对话，注意节奏感。
  第4步「转场过渡」：场景之间用 1-2 句环境/心理过渡，保持叙事流畅。

═══════════════════════════════════
【输出要求】
- 直接输出正文，不要写「场景1」「第1步」等标签。
- 字数严格控制在 3000-6000 字。
- 结尾必须产生强烈的「必须翻到下一页」的钩子效果。
"""


def build_chapter_continue_prompt(word_count: int, existing_content: str) -> str:
    """字数不足时扩展内容的提示词"""
    return (
        f"当前章节内容字数 {word_count}，不足 3000 字。\n"
        f"请继续扩展内容。优先补充：\n"
        f"1. 关键冲突处的慢镜头扩写（生理反应 + 环境映射）\n"
        f"2. 对话中的潜台词与留白\n"
        f"3. 场景转场的过渡描写\n\n"
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
