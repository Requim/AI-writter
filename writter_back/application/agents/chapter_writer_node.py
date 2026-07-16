"""章节内容填充节点 - 场景队列生成 + 动态字数校准

策略：
1. 场景数 >= 3 → 场景队列生成：逐个场景生成，上下文透传 + 动态校准
2. 场景数 < 3 → 降级到传统单次生成
"""

import logging

logger = logging.getLogger("uvicorn")
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal
from application.schemas.agent_state import NovelAgentState
from application.continuity import build_story_bible
from application.streaming import collect_streamed_text, emit_workflow_event
from service.ports.llm_service import LLMService
from application.prompts.chapter_writer_prompts import (
    build_chapter_writer_prompt,
    build_first_scene_prompt,
    build_next_scene_prompt,
    build_scene_continue_prompt,
    build_chapter_continue_prompt,
    build_chapter_system_prompt,
    CHAPTER_WRITER_TEMPERATURE,
)

# 字数约束常量
MIN_WORDS = 3000
MAX_WORDS = 7000
TRUNCATE_TRIGGER = 7500  # 超过此值触发截断（给语义截断留缓冲）
TARGET_CHAPTER_WORDS = 5000  # 整章理想字数

# 场景队列生成参数
SCENE_QUEUE_MIN_SCENES = 3  # 至少3个场景才启用队列生成
FIRST_SCENE_WEIGHT = 1.1  # 第一场景字数权重（略多）
MAX_SCENE_WORDS_RATIO = 1.5  # 单场景最大倍数（相对目标）


def _semantic_truncate(text: str, target: int = MAX_WORDS) -> str:
    """按中文语义边界截断文本，在最近的句子结束处截断"""
    if len(text) <= target:
        return text

    # 从 target 位置往回找最近的中文句末标点
    search_start = max(target - 1500, 0)
    sentence_endings = {"。", "！", "？", "…", "\n"}
    for i in range(target, search_start, -1):
        if i < len(text) and text[i] in sentence_endings:
            return text[: i + 1] + "\n\n[内容已截断，原稿过长，后续内容省略]"

    # 找不到句末标点，找段落换行
    for i in range(target, search_start, -1):
        if i < len(text) and text[i] == "\n":
            return text[:i] + "\n\n[内容已截断，原稿过长，后续内容省略]"

    # 兜底：在 target 处直接截断（带省略提示）
    return text[:target] + "\n\n[内容已截断，原稿过长，后续内容省略]"


def _distribute_scene_targets(num_scenes: int) -> list[int]:
    """将整章目标字数分配到各场景

    第一场景权重 1.1，其余均匀分布，确保总和 = TARGET_CHAPTER_WORDS
    """
    if num_scenes <= 0:
        return []
    if num_scenes == 1:
        return [TARGET_CHAPTER_WORDS]
    base = TARGET_CHAPTER_WORDS // num_scenes
    targets = [int(base * FIRST_SCENE_WEIGHT)] + [base] * (num_scenes - 1)
    # 调整使总和精确等于 TARGET_CHAPTER_WORDS
    diff = TARGET_CHAPTER_WORDS - sum(targets)
    targets[-1] += diff
    # 确保每场景不低于 800 字
    targets = [max(800, t) for t in targets]
    return targets


def _build_prev_scene_digest(scene_outline: dict, generated_content: str) -> str:
    """构建上一场景的摘要（用于上下文透传）

    同时保留细纲落点和真实正文末尾，避免模型根据计划而不是已经写出的事实续接。
    """
    events = scene_outline.get("events", {})
    if isinstance(events, dict):
        result = events.get("result", "")
        entry = events.get("entry", "")
        struggle = events.get("struggle", "")
        if result:
            digest = f"场景落点：{result}"
            if struggle:
                digest += f"\n冲突核心：{struggle[:100]}"
            if generated_content:
                digest += f"\n上一场景真实结尾：\n{generated_content[-700:].strip()}"
            return digest
        if entry:
            digest = f"场景概述：{entry[:100]} → {struggle[:100] if struggle else ''}"
            if generated_content:
                digest += f"\n上一场景真实结尾：\n{generated_content[-700:].strip()}"
            return digest
    # 兜底：从生成内容取结尾
    return generated_content[-700:].strip() if generated_content else ""


def _calibrate_next_scene(
    prev_word_count: int,
    prev_target: int,
    next_target: int,
) -> tuple[int, str]:
    """动态字数校准：根据上一场景实际字数调整下一场景目标

    Returns:
        (adjusted_target, correction_note)
    """
    ratio = prev_word_count / prev_target if prev_target > 0 else 1.0

    if ratio < 0.7:
        # 上一场景太短 → 下一场景需要补偿
        deficit = prev_target - prev_word_count
        boost = int(deficit * 0.5)
        adjusted = next_target + boost
        note = (
            f"⚠️ 上一场景节奏过快（仅{prev_word_count}字，目标{prev_target}字），"
            f"请在接下来的场景中加强环境细节和对话博弈，补足字数缺口。"
            f"本场景目标已上调至{adjusted}字。"
        )
        return adjusted, note

    elif ratio > 1.3:
        # 上一场景太长 → 适度精简
        excess = prev_word_count - prev_target
        reduce = int(excess * 0.3)
        adjusted = max(800, next_target - reduce)
        note = (
            f"上一场景篇幅较长（{prev_word_count}字），"
            f"请在接下来的场景中保持节奏，不必刻意拉长，"
            f"聚焦于核心情节推进和信息增量。"
        )
        return adjusted, note

    else:
        # 正常范围，不作调整
        return next_target, ""


async def _scene_queue_generate(
    scenes: list[dict],
    chapter_outline: dict,
    novel_type: str,
    title: str,
    memory_context: str,
    llm: LLMService,
    chapter_index: int,
    prev_chapter_tail: str = "",
    story_bible: str = "",
) -> str:
    """场景队列生成：逐个场景生成，每步上下文透传 + 动态校准"""
    chapter_num = chapter_outline.get("chapter_number", "?")
    ch_title = chapter_outline.get("title", "")
    internal_monologue = chapter_outline.get("internal_monologue", "")
    logic_hooks = chapter_outline.get("logic_hooks", {})
    num_scenes = len(scenes)

    # 1. 字数分配
    targets = _distribute_scene_targets(num_scenes)
    logger.info(f"【场景队列】{num_scenes}个场景，字数目标分配: {targets}")

    scene_contents: list[str] = []
    adjusted_targets: list[int] = []

    for i, scene in enumerate(scenes):
        is_first = i == 0
        target = targets[i]

        # 统一系统提示词
        system_prompt = build_chapter_system_prompt(novel_type)

        if is_first:
            # ── Prompt A: 第一个场景（全量上下文） ──
            prompt = build_first_scene_prompt(
                scene=scene,
                chapter_outline=chapter_outline,
                novel_type=novel_type,
                title=title,
                chapter_num=chapter_num,
                ch_title=ch_title,
                memory_context=memory_context,
                target_words=target,
                total_scenes=num_scenes,
                logic_hooks=logic_hooks,
                internal_monologue=internal_monologue,
                prev_chapter_tail=prev_chapter_tail,
                story_bible=story_bible,
            )
        else:
            # ── Prompt B: 后续场景（上下文透传 + 校准） ──
            prev_scene = scenes[i - 1]
            prev_content = scene_contents[-1]
            prev_count = len(prev_content)
            prev_target = adjusted_targets[-1] if adjusted_targets else targets[i - 1]

            # 动态字数校准
            adjusted_target, correction_note = _calibrate_next_scene(
                prev_count,
                prev_target,
                target,
            )

            # 构建上一场景摘要
            prev_digest = _build_prev_scene_digest(prev_scene, prev_content)

            prompt = build_next_scene_prompt(
                scene=scene,
                chapter_outline=chapter_outline,
                novel_type=novel_type,
                title=title,
                chapter_num=chapter_num,
                ch_title=ch_title,
                scene_index=i + 1,
                total_scenes=num_scenes,
                prev_scene_digest=prev_digest,
                prev_word_count=prev_count,
                correction_note=correction_note,
                target_words=adjusted_target,
                logic_hooks=logic_hooks,
                internal_monologue=internal_monologue,
                memory_context=memory_context,
                story_bible=story_bible,
            )
            target = adjusted_target

        scene_tag = f"场景{i + 1}/{num_scenes}"
        logger.info(
            f"【场景队列】生成{scene_tag} (目标:{target}字, "
            f"{'首场景' if is_first else '后续'})",
        )

        # ── 生成场景内容 ──
        content = await collect_streamed_text(
            llm,
            prompt=prompt,
            node="chapter_writer_node",
            chapter_index=chapter_index,
            system_prompt=system_prompt,
            temperature=CHAPTER_WRITER_TEMPERATURE,
            prefix="\n\n" if i > 0 else "",
        )
        actual_count = len(content)
        logger.info(f"【场景队列】{scene_tag} 生成完成: {actual_count}字")

        # ── 单场景字数不足 → 续写 ──
        min_scene_words = max(600, target // 2)
        if actual_count < min_scene_words:
            logger.info(
                f"【场景队列】{scene_tag} 字数不足 ({actual_count}<{min_scene_words})，"
                f"正在扩展...",
            )
            correction = (
                f"注意：当前场景目前仅{actual_count}字，远低于目标{target}字。"
                f"请在保持质量的前提下充实描写和情节。"
            )
            extra_prompt = build_scene_continue_prompt(
                word_count=actual_count,
                target_words=target,
                existing_content=content,
                correction_note=correction,
            )
            extra = await collect_streamed_text(
                llm,
                extra_prompt,
                node="chapter_writer_node",
                chapter_index=chapter_index,
                temperature=CHAPTER_WRITER_TEMPERATURE,
                prefix="\n\n",
            )
            content += extra
            logger.info(
                f"【场景队列】{scene_tag} 扩展后: {len(content)}字",
            )

        scene_contents.append(content)
        adjusted_targets.append(target)

    # 2. 拼接所有场景
    logger.info("【场景队列】所有场景生成完成, 准备拼接...")
    full_content = "\n\n".join(scene_contents)
    logger.info(f"【场景队列】拼接后总字数: {len(full_content)}字")

    return full_content


async def _final_word_check(
    content: str,
    llm: LLMService,
    system_prompt: str,
    chapter_index: int,
) -> str:
    """最终字数检查：不足则扩展（不再截断）"""
    word_count = len(content)

    if word_count < MIN_WORDS:
        logger.info(f"【字数检查】字数不足 ({word_count}字)，正在扩展内容...")
        continue_prompt = build_chapter_continue_prompt(word_count, content)
        additional_content = await collect_streamed_text(
            llm,
            continue_prompt,
            node="chapter_writer_node",
            chapter_index=chapter_index,
            system_prompt=system_prompt,
            temperature=CHAPTER_WRITER_TEMPERATURE,
            prefix="\n\n",
        )
        content += additional_content
        logger.info(f"【字数检查】扩展后字数: {len(content)}字")
    else:
        logger.info(f"【字数检查】字数合格: {word_count}字")

    return content


async def _get_prev_chapter_tail(
    config: RunnableConfig, novel_id: str, current_chapter_index: int
) -> str:
    """从 DB 获取上一章正文末尾 1000 字，用于衔接"""
    repository = config["configurable"].get("novel_repository")
    if not repository or current_chapter_index <= 0:
        return ""
    try:
        tenant_id = config["configurable"].get("tenant_id", "")
        novel = await repository.find_by_id_with_chapters(tenant_id, novel_id)
        if not novel or not hasattr(novel, "chapters"):
            return ""
        chapters_sorted = sorted(novel.chapters, key=lambda c: c.chapter_index)
        prev_ch = None
        for ch in chapters_sorted:
            if ch.chapter_index == current_chapter_index - 1:
                prev_ch = ch
                break
        if not prev_ch or not prev_ch.content:
            return ""
        tail = prev_ch.content[-1000:]
        logger.info(
            f"【章节写作节点】已获取上一章(#{current_chapter_index})末尾 {len(tail)}字 用于衔接"
        )
        return tail
    except Exception as e:
        logger.info(f"【章节写作节点】获取上一章尾部失败(降级): {e}")
        return ""


async def chapter_writer_node(
    state: NovelAgentState,
    config: RunnableConfig,
) -> Command[Literal["router_agent"]]:
    """
    章节内容填充节点 - 场景队列生成 + 动态字数校准
    当细纲 scenes >= 3 时启用场景队列，否则降级到单次生成。
    """
    chapter_outline = state.get("chapter_outlines", [{}])[-1]
    novel_type = state.get("novel_type", "")
    title = state.get("title", "")
    memory_context = state.get("memory_context", "")
    total_outline_raw = state.get("total_outline", {})
    total_outline = total_outline_raw if isinstance(total_outline_raw, dict) else {}
    story_bible = build_story_bible(total_outline)
    chapter_num = chapter_outline.get("chapter_number", "?")
    has_llm = bool(config["configurable"].get("llm_config", {}).get("llm_instance"))
    llm_status = "✅ 已加载" if has_llm else "❌ 不可用"
    logger.info(f"{'=' * 60}")
    logger.info(
        f"【章节写作节点】进入 | 书名={title}, 第{chapter_num}章, LLM={llm_status}",
    )

    # 从 config.configurable 获取 LLM 实例
    llm_config = config["configurable"].get("llm_config", {})
    llm = llm_config.get("llm_instance")

    if not llm:
        raise RuntimeError("章节正文生成失败：LLM 不可用")

    quota_service = config["configurable"].get("quota_service")
    tenant_context = config["configurable"].get("tenant_context")
    workflow_run_id = state.get("workflow_run_id")
    current_idx = state.get("current_chapter_index", 0)
    if (
        quota_service
        and tenant_context
        and workflow_run_id
        and not config["configurable"].get("quota_operation_pre_reserved", False)
    ):
        await quota_service.reserve(
            tenant_context,
            workflow_run_id,
            "chapter",
            current_idx,
        )

    # 判断使用场景队列还是降级
    scenes = chapter_outline.get("scenes", [])
    use_scene_queue = len(scenes) >= SCENE_QUEUE_MIN_SCENES
    system_prompt = build_chapter_system_prompt(novel_type)

    # 获取上一章尾部用于衔接（只在非第一章时有效）
    novel_id = config["configurable"].get("novel_id", "")
    emit_workflow_event(
        "content_delta",
        {"chapter_index": current_idx, "operation": "reset", "text": ""},
        "chapter_writer_node",
    )
    prev_tail = await _get_prev_chapter_tail(config, novel_id, current_idx)

    if use_scene_queue:
        logger.info(
            f"【章节写作节点】场景队列模式 | {len(scenes)}个场景",
        )
        # 场景队列模式下，prev_tail 传给第一个场景 prompt
        content = await _scene_queue_generate(
            scenes=scenes,
            chapter_outline=chapter_outline,
            novel_type=novel_type,
            title=title,
            memory_context=memory_context,
            llm=llm,
            chapter_index=current_idx,
            prev_chapter_tail=prev_tail,
            story_bible=story_bible,
        )
    else:
        logger.info(
            f"【章节写作节点】保守模式（场景数={len(scenes)} < {SCENE_QUEUE_MIN_SCENES}）",
        )
        prompt = build_chapter_writer_prompt(
            chapter_outline,
            novel_type,
            title,
            memory_context,
            prev_chapter_tail=prev_tail,
            story_bible=story_bible,
        )
        content = await collect_streamed_text(
            llm,
            prompt=prompt,
            node="chapter_writer_node",
            chapter_index=current_idx,
            system_prompt=system_prompt,
            temperature=CHAPTER_WRITER_TEMPERATURE,
        )

    # 最终字数检查（不足则扩展，不再截断）
    content = await _final_word_check(content, llm, system_prompt, current_idx)

    logger.info(
        f"【章节写作节点】完成 -> 路由节点 | 最终字数: {len(content)}字",
    )
    logger.info(f"{'=' * 60}")
    return Command(
        goto="router_agent",
        update={
            "current_chapter_content": content,
            "revision_attempts": 0,  # 新章节重置修正计数器
        },
    )
