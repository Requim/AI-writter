"""Chapter drafting with bounded scene queues and deterministic routing."""

import logging
from dataclasses import dataclass
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.continuity import build_story_bible
from application.prompts.chapter_writer_prompts import (
    CHAPTER_WRITER_TEMPERATURE,
    build_chapter_continue_prompt,
    build_chapter_system_prompt,
    build_chapter_writer_prompt,
)
from application.scene_queue import (
    SceneQueueContext,
    build_previous_scene_digest,
    build_scene_ledger_entry,
    generate_scene_queue,
)
from application.schemas.agent_state import NovelAgentState
from application.streaming import collect_streamed_text, emit_workflow_event
from service.ports.llm_service import LLMService

logger = logging.getLogger("uvicorn")


def _build_prev_scene_digest(scene: dict, content: str) -> str:
    """兼容旧调用方的场景摘要入口。"""
    return build_previous_scene_digest(scene, content)


def _build_scene_ledger_entry(
    scene_index: int, scene_outline: dict, generated_content: str
) -> dict:
    """兼容旧调用方的场景账本入口。"""
    return build_scene_ledger_entry(scene_index, scene_outline, generated_content)
MIN_WORDS = 3000
SCENE_QUEUE_MIN_SCENES = 2


@dataclass(frozen=True)
class ChapterDraftContext:
    outline: dict
    novel_type: str
    title: str
    memory_context: str
    story_bible: str
    chapter_index: int
    previous_tail: str
    total_outline: dict


async def _final_word_check(
    content: str, llm: LLMService, system_prompt: str, chapter_index: int
) -> str:
    """Expand only drafts that remain below the minimum chapter length."""
    if len(content) >= MIN_WORDS:
        return content
    prompt = build_chapter_continue_prompt(len(content), content)
    extra = await collect_streamed_text(
        llm, prompt, node="chapter_writer_node", chapter_index=chapter_index,
        system_prompt=system_prompt, temperature=CHAPTER_WRITER_TEMPERATURE,
        prefix="\n\n",
    )
    return content + extra


async def _get_prev_chapter_tail(
    config: RunnableConfig, novel_id: str, chapter_index: int
) -> str:
    """Load the previous persisted chapter ending for continuity."""
    repository = config["configurable"].get("novel_repository")
    if not repository or chapter_index <= 0:
        return ""
    try:
        tenant_id = config["configurable"].get("tenant_id", "")
        novel = await repository.find_by_id_with_chapters(tenant_id, novel_id)
        chapters = sorted(getattr(novel, "chapters", []), key=lambda item: item.chapter_index)
        previous = next((item for item in chapters if item.chapter_index == chapter_index - 1), None)
        return str(getattr(previous, "content", "") or "")[-1000:]
    except Exception as exc:
        logger.info("【章节写作节点】读取上一章失败，使用降级上下文 | %s", exc)
        return ""


def _draft_context(state: NovelAgentState, previous_tail: str) -> ChapterDraftContext:
    outline = (state.get("chapter_outlines") or [{}])[-1]
    total = state.get("total_outline")
    outline = outline if isinstance(outline, dict) else {}
    total = total if isinstance(total, dict) else {}
    return ChapterDraftContext(
        outline=outline,
        novel_type=str(state.get("novel_type") or ""),
        title=str(state.get("title") or ""),
        memory_context=str(state.get("memory_context") or ""),
        story_bible=build_story_bible(total, related_context=outline),
        chapter_index=state.get("current_chapter_index", 0),
        previous_tail=previous_tail,
        total_outline=total,
    )


async def _reserve_quota(state: NovelAgentState, config: RunnableConfig) -> None:
    values = config["configurable"]
    service = values.get("quota_service")
    context = values.get("tenant_context")
    run_id = state.get("workflow_run_id")
    if not service or not context or not run_id:
        return
    if values.get("quota_operation_pre_reserved", False):
        return
    await service.reserve(context, run_id, "chapter", state.get("current_chapter_index", 0))


async def _conservative_generate(context: ChapterDraftContext, llm: LLMService) -> str:
    prompt = build_chapter_writer_prompt(
        context.outline, context.novel_type, context.title, context.memory_context,
        prev_chapter_tail=context.previous_tail, story_bible=context.story_bible,
        creative_brief=context.total_outline.get("creative_brief", {}),
    )
    return await collect_streamed_text(
        llm, prompt, node="chapter_writer_node", chapter_index=context.chapter_index,
        system_prompt=build_chapter_system_prompt(context.novel_type),
        temperature=CHAPTER_WRITER_TEMPERATURE,
    )


async def _generate_draft(
    context: ChapterDraftContext, llm: LLMService
) -> tuple[str, list[dict]]:
    scenes = context.outline.get("scenes", [])
    if isinstance(scenes, list) and len(scenes) >= SCENE_QUEUE_MIN_SCENES:
        queue = SceneQueueContext(
            scenes=scenes, chapter_outline=context.outline,
            novel_type=context.novel_type, title=context.title,
            memory_context=context.memory_context, llm=llm,
            chapter_index=context.chapter_index, previous_tail=context.previous_tail,
            story_bible=context.story_bible,
            total_outline=context.total_outline,
        )
        return await generate_scene_queue(queue)
    return await _conservative_generate(context, llm), []


def _draft_command(content: str, ledger: list[dict]) -> Command:
    return Command(
        goto="router_agent",
        update={
            "current_chapter_content": content,
            "revision_attempts": 0,
            "scene_ledger": ledger,
            "compaction_checked": False,
            "compaction_metrics": {},
        },
    )


async def chapter_writer_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["router_agent"]]:
    """Generate one chapter and leave review decisions to downstream nodes."""
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        raise RuntimeError("章节正文生成失败：LLM 不可用")
    emit_workflow_event(
        "status", {"status": "started", "message": "正在生成章节正文"},
        "chapter_writer_node",
    )
    await _reserve_quota(state, config)
    index = state.get("current_chapter_index", 0)
    emit_workflow_event(
        "content_delta", {"chapter_index": index, "operation": "reset", "text": ""},
        "chapter_writer_node",
    )
    novel_id = str(config["configurable"].get("novel_id") or "")
    previous_tail = await _get_prev_chapter_tail(config, novel_id, index)
    context = _draft_context(state, previous_tail)
    content, ledger = await _generate_draft(context, llm)
    system_prompt = build_chapter_system_prompt(context.novel_type)
    content = await _final_word_check(content, llm, system_prompt, index)
    logger.info("【章节写作节点】完成 | 第%s章, %s字", index + 1, len(content))
    return _draft_command(content, ledger)
