"""Scene-queue generation kept separate from workflow routing."""

import logging
from dataclasses import dataclass, field

from application.continuity import build_story_bible
from application.prompts.chapter_writer_prompts import (
    CHAPTER_WRITER_TEMPERATURE,
    build_chapter_system_prompt,
    build_first_scene_prompt,
    build_next_scene_prompt,
    build_scene_continue_prompt,
)
from application.streaming import collect_streamed_text
from application.word_budget import chapter_target_words
from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")
FIRST_SCENE_WEIGHT = 1.1


@dataclass
class SceneQueueContext:
    scenes: list[dict]
    chapter_outline: dict
    novel_type: str
    title: str
    memory_context: str
    llm: LLMService
    chapter_index: int
    previous_tail: str = ""
    story_bible: str = ""
    total_outline: dict = field(default_factory=dict)
    targets: list[int] = field(default_factory=list)
    contents: list[str] = field(default_factory=list)
    ledger: list[dict] = field(default_factory=list)


def distribute_scene_targets(scene_count: int, total_target: int) -> list[int]:
    """Distribute a chapter-specific budget without exceeding its total."""
    if scene_count <= 0:
        return []
    if scene_count == 1:
        return [total_target]
    weights = [FIRST_SCENE_WEIGHT] + [1.0] * (scene_count - 1)
    weight_total = sum(weights)
    targets = [int(total_target * weight / weight_total) for weight in weights]
    targets[-1] += total_target - sum(targets)
    return targets


def build_scene_ledger_entry(
    scene_index: int, scene_outline: dict, generated_content: str, target: int = 0
) -> dict:
    """Record planned obligations, budget and the actual ending."""
    events = scene_outline.get("events", {})
    result = events.get("result", "") if isinstance(events, dict) else ""
    paragraphs = [item.strip() for item in generated_content.splitlines() if item.strip()]
    return {
        "scene_index": scene_index,
        "planned_result": result,
        "planned_turn": scene_outline.get("turn", ""),
        "planned_price_paid": scene_outline.get("price_paid", ""),
        "planned_state_delta": scene_outline.get("state_delta", ""),
        "actual_ending": paragraphs[-1][-500:] if paragraphs else generated_content[-500:],
        "actual_character_count": len(generated_content),
        "target_character_count": target,
    }


def build_previous_scene_digest(scene: dict, content: str) -> str:
    events = scene.get("events", {})
    if not isinstance(events, dict):
        return content[-700:].strip()
    result = str(events.get("result") or "").strip()
    struggle = str(events.get("struggle") or "").strip()
    summary = f"场景落点：{result}" if result else f"场景概述：{events.get('entry', '')}"
    if struggle:
        summary += f"\n冲突核心：{struggle[:100]}"
    if content:
        summary += f"\n上一场景真实结尾：\n{content[-700:].strip()}"
    return summary


def _calibrate_target(previous_count: int, previous_target: int, target: int) -> tuple[int, str]:
    ratio = previous_count / previous_target if previous_target else 1.0
    if ratio > 1.2:
        reduction = min(int((previous_count - previous_target) * 0.5), target // 4)
        return max(600, target - reduction), "上一场景超出预算；只完成未履行的行动与信息增量，避免重复解释。"
    if ratio < 0.7:
        return target, "上一场景较短；优先补齐行动、反制、转折和代价，不得用环境描写凑字数。"
    return target, ""


def _scene_prompt(context: SceneQueueContext, index: int, target: int) -> tuple[str, int]:
    outline = context.chapter_outline
    related = {
        "pov_character": outline.get("pov_character", ""),
        "scene": context.scenes[index],
    }
    story_bible = (
        build_story_bible(context.total_outline, related_context=related)
        if context.total_outline
        else context.story_bible
    )
    common = {
        "scene": context.scenes[index], "chapter_outline": outline,
        "novel_type": context.novel_type, "title": context.title,
        "chapter_num": outline.get("chapter_number", "?"), "ch_title": outline.get("title", ""),
        "total_scenes": len(context.scenes),
        "logic_hooks": outline.get("logic_hooks", {}),
        "internal_monologue": outline.get("internal_monologue", ""),
    }
    if index == 0:
        return build_first_scene_prompt(
            **common, target_words=target, memory_context=context.memory_context,
            prev_chapter_tail=context.previous_tail, story_bible=story_bible,
        ), target
    previous_target = context.ledger[-1].get("target_character_count", context.targets[index - 1])
    adjusted, note = _calibrate_target(len(context.contents[-1]), previous_target, target)
    return build_next_scene_prompt(
        **common, scene_index=index + 1,
        prev_scene_digest=build_previous_scene_digest(context.scenes[index - 1], context.contents[-1]),
        prev_word_count=len(context.contents[-1]), correction_note=note,
        memory_context=context.memory_context, story_bible=story_bible,
        scene_ledger=context.ledger, target_words=adjusted,
    ), adjusted


async def _extend_short_scene(
    context: SceneQueueContext, content: str, target: int
) -> str:
    if len(content) >= max(600, target // 2):
        return content
    prompt = build_scene_continue_prompt(
        len(content), target, content,
        "只补齐尚未完成的行动、反制、信息增量和不可逆代价。",
    )
    extra = await collect_streamed_text(
        context.llm, prompt, node="chapter_writer_node",
        chapter_index=context.chapter_index, temperature=CHAPTER_WRITER_TEMPERATURE,
        prefix="\n\n",
    )
    return content + extra


async def _generate_scene(context: SceneQueueContext, index: int) -> None:
    prompt, target = _scene_prompt(context, index, context.targets[index])
    content = await collect_streamed_text(
        context.llm, prompt, node="chapter_writer_node",
        chapter_index=context.chapter_index,
        system_prompt=build_chapter_system_prompt(context.novel_type),
        temperature=CHAPTER_WRITER_TEMPERATURE,
        prefix="\n\n" if index else "",
    )
    content = await _extend_short_scene(context, content, target)
    context.contents.append(content)
    context.ledger.append(build_scene_ledger_entry(index + 1, context.scenes[index], content, target))
    logger.info("【场景队列】场景%s/%s 完成: %s字", index + 1, len(context.scenes), len(content))


async def generate_scene_queue(context: SceneQueueContext) -> tuple[str, list[dict]]:
    """Generate each scene once and return the chapter plus execution ledger."""
    total_target = chapter_target_words(context.chapter_outline)
    context.targets = distribute_scene_targets(len(context.scenes), total_target)
    logger.info("【场景队列】目标=%s, 分配=%s", total_target, context.targets)
    for index in range(len(context.scenes)):
        await _generate_scene(context, index)
    content = "\n\n".join(context.contents)
    logger.info("【场景队列】拼接后总字数: %s字", len(content))
    return content, context.ledger
