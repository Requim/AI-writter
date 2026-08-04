"""章节写作提示词（兼容新旧细纲格式 + 场景队列生成）

优化点：
1. 解决"中途乏力"：信息密度 + 段落权重 + 均匀分布
2. 强化"逻辑钩子"强制执行：前10%回收Callback，后10%埋设Setup
3. 提升对话"非直接性"：动作辅助对话，禁止连续纯对白
4. 场景队列生成：逐个场景生成（用于 node 侧调度）
"""

import json

from application.continuity import (
    build_budgeted_context,
    compact_story_bible,
    compact_text,
)
from application.prompts.template_loader import render_prompt
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
        parts = [
            json.dumps(item, ensure_ascii=False) if isinstance(item, dict) else str(item)
            for item in sensory
        ]
        return "\n    ".join(item for item in parts if item) or "无"
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
    sensory = _fmt_sensory(
        scene.get("sensory_anchors", scene.get("sensory_details"))
    )
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


def _writing_principles() -> str:
    return render_prompt("chapter/writing_principles.txt")


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

    return render_prompt(
        "chapter/first_scene.txt",
        chapter_num=chapter_num,
        total_scenes=total_scenes,
        novel_type=novel_type,
        title=title,
        chapter_title=ch_title,
        target_words=target_words,
        scene_block=scene_block,
        story_bible=compact_story_bible(story_bible, 2600) if story_bible else "无",
        contract=contract,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=callback_str,
        setup=setup_str,
        memory_context=ctx,
        previous_tail=prev_tail_block,
        writing_principles=_writing_principles(),
    )


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

    return render_prompt(
        "chapter/next_scene.txt",
        chapter_num=chapter_num,
        scene_index=scene_index,
        total_scenes=total_scenes,
        novel_type=novel_type,
        title=title,
        chapter_title=ch_title,
        target_words=target_words,
        previous_digest=prev_scene_digest,
        ledger=ledger or "无",
        story_bible=compact_story_bible(story_bible, 2200) if story_bible else "无",
        contract=contract,
        scene_block=scene_block,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=callback_str,
        setup=setup_str,
        memory_context=ctx,
        correction=correction,
        writing_principles=_writing_principles(),
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
    correction = f"【动态校准】{correction_note}\n" if correction_note else ""
    return render_prompt(
        "chapter/scene_continue.txt",
        word_count=word_count,
        target_words=target_words,
        correction_note=correction,
        writing_principles=_writing_principles(),
        existing_tail=existing_content[-800:],
    )


# ─────────────────────────────────────────────
#  保守模式（单次生成整章，用于降级)
# ─────────────────────────────────────────────

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

    return render_prompt(
        "chapter/full_chapter.txt",
        chapter_number=ch_num,
        novel_type=novel_type,
        title=title,
        chapter_title=ch_title,
        word_distribution=word_dist or "3000-7000字",
        target_words=chapter_target_words(chapter_outline),
        scenes=scenes_text,
        story_bible=compact_story_bible(story_bible, 2600) if story_bible else "无",
        contract=contract,
        internal_monologue=internal_monologue or "无特殊要求",
        callback=logic_hooks.get("callback", "无"),
        setup=logic_hooks.get("setup", "无"),
        memory_context=ctx,
        previous_tail=prev_tail_block,
        writing_principles=_writing_principles(),
    )


def build_chapter_continue_prompt(word_count: int, existing_content: str) -> str:
    """字数不足时扩展内容的提示词（降级模式用）"""
    return render_prompt(
        "chapter/chapter_continue.txt",
        word_count=word_count,
        writing_principles=_writing_principles(),
        existing_tail=existing_content[-800:],
    )


def build_chapter_system_prompt(novel_type: str) -> str:
    """章节写作的系统提示词"""
    return render_prompt("chapter/system.txt", novel_type=novel_type)


CHAPTER_WRITER_TEMPERATURE = 0.78
