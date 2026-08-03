"""Tenant-scoped novel, chapter and rewrite endpoints."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from api.dependencies import get_tenant_context
from application.checkpoint_reconciliation import reconcile_pending_checkpoint
from application.errors import QualityGateReviewRequired, WorkflowBusyError
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from infrastructure.database.identity_repository import (
    AIUnavailableError,
    QuotaExceededError,
)
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress

router = APIRouter()
REWRITE_MAX_REVISION_ATTEMPTS = 5
REWRITE_MAX_NODE_STEPS = REWRITE_MAX_REVISION_ATTEMPTS * 2 + 2


def get_repository(request: Request) -> PostgresNovelRepository:
    return request.app.state.repository


class NovelCreateRequest(BaseModel):
    novel_type: str
    title: str | None = None
    summary: str | None = None
    total_outline: dict[str, Any] | None = None


class NovelResponse(BaseModel):
    id: str
    novel_type: str
    title: str | None
    summary: str | None
    status: str
    progress_percentage: float = 0.0
    thread_id: str | None = None
    total_outline: dict[str, Any] | None = None


class ProgressResponse(BaseModel):
    current_chapter: int
    total_chapters: int
    percentage: float
    status: str


class ChapterResponse(BaseModel):
    id: str
    chapter_index: int
    title: str
    word_count: int
    status: str
    version: int


class ChapterUpdateRequest(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class ChapterDetailResponse(ChapterResponse):
    content: str
    updated_at: datetime
    checkpoint_status: str | None = None


class ChapterBatchDeleteRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1)


def _tenant_id(context: TenantContext) -> str:
    return str(context.tenant_id)


def _novel_response(novel: Novel) -> NovelResponse:
    outline = novel.total_outline
    total_outline = (
        outline.__dict__
        if outline and hasattr(outline, "__dict__")
        else (outline if isinstance(outline, dict) else None)
    )
    return NovelResponse(
        id=str(novel.id),
        novel_type=novel.novel_type,
        title=novel.title,
        summary=novel.summary,
        status=novel.progress.status if novel.progress else "draft",
        progress_percentage=novel.progress.percentage if novel.progress else 0.0,
        thread_id=novel.thread_id,
        total_outline=total_outline,
    )


def _chapter_response(
    chapter: Any, checkpoint_status: str | None = None
) -> ChapterDetailResponse:
    return ChapterDetailResponse(
        id=str(chapter.id),
        chapter_index=chapter.chapter_index,
        title=chapter.title or f"第{chapter.chapter_index + 1}章",
        content=chapter.content or "",
        word_count=chapter.word_count,
        status=chapter.status,
        version=chapter.version,
        updated_at=chapter.updated_at,
        checkpoint_status=checkpoint_status,
    )


def _workflow_busy_error(exc: WorkflowBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "novel_busy", "message": str(exc)},
    )


@router.post("", response_model=dict, status_code=201)
async def create_novel(
    payload: NovelCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    try:
        valid_type = NovelType(payload.novel_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的小说类型") from exc
    outline = Outline(**payload.total_outline) if payload.total_outline else None
    novel_id = uuid4()
    novel = Novel(
        id=novel_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        novel_type=valid_type.value,
        title=payload.title,
        summary=payload.summary,
        total_outline=outline,
        progress=Progress(),
        thread_id=str(novel_id),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    saved = await repo.save(_tenant_id(context), novel)
    return {
        "novel_id": str(saved.id),
        "thread_id": novel.thread_id,
        "status": "created",
    }


@router.get("", response_model=list[NovelResponse])
async def list_novels(
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    return [
        _novel_response(novel) for novel in await repo.find_all(_tenant_id(context))
    ]


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return _novel_response(novel)


@router.get("/{novel_id}/progress", response_model=ProgressResponse)
async def get_progress(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    progress = novel.progress or Progress()
    return ProgressResponse(
        current_chapter=progress.current_chapter,
        total_chapters=progress.total_chapters,
        percentage=progress.percentage,
        status=progress.status,
    )


@router.get("/{novel_id}/chapters", response_model=list[ChapterResponse])
async def list_chapters(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id_with_chapters(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return [
        ChapterResponse(
            id=str(chapter.id),
            chapter_index=chapter.chapter_index,
            title=chapter.title,
            word_count=chapter.word_count,
            status=chapter.status,
            version=chapter.version,
        )
        for chapter in novel.chapters
    ]


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(
    novel_id: str,
    chapter_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    if chapter is None or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    return _chapter_response(chapter)


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def update_chapter(
    novel_id: str,
    chapter_id: str,
    payload: ChapterUpdateRequest,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    try:
        async with orchestrator.exclusive_operation(
            context, novel_id, "正在保存章节修改"
        ):
            chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
            if chapter is None or str(chapter.novel_id) != novel_id:
                raise HTTPException(status_code=404, detail="章节不存在")
            chapter.title = (
                payload.title.strip()
                or chapter.title
                or f"第{chapter.chapter_index + 1}章"
            )
            chapter.content = payload.content
            chapter.word_count = len(payload.content)
            chapter.updated_at = datetime.now()
            memory = request.app.state.memory_service
            memory_content, memory_metadata = memory.build_chapter_memory(
                chapter.__dict__
            )
            saved = await repo.update_chapter_consistently(
                _tenant_id(context),
                novel_id,
                chapter,
                payload.expected_version,
                memory_content,
                memory_metadata,
                f"{chapter.title}\n\n{payload.content[:1200]}",
            )
            if saved is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "chapter_version_conflict",
                        "message": "章节已在其他窗口更新，请重新载入后再保存",
                    },
                )
            checkpoint_status = await reconcile_pending_checkpoint(
                repo, orchestrator, context, novel_id
            )
            return _chapter_response(saved, checkpoint_status)
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc


def _rewrite_config(
    request: Request,
    context: TenantContext,
    novel_id: str,
    repo: PostgresNovelRepository,
    quota: QuotaService,
    orchestrator: NovelOrchestrator,
) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": f"{context.tenant_id}:{novel_id}",
            "public_thread_id": novel_id,
            "novel_id": novel_id,
            "tenant_id": _tenant_id(context),
            "tenant_context": context,
            "novel_repository": repo,
            "memory_service": request.app.state.memory_service,
            "quota_service": quota,
            "quota_operation_pre_reserved": True,
            "auto_mode": True,
            "direct_rewrite": True,
            "max_reflection_loops": REWRITE_MAX_REVISION_ATTEMPTS,
            "discard_following_chapters": True,
            "llm_config": {"llm_instance": orchestrator._get_llm_instance()},
        }
    }


def _rewrite_state(
    novel: Novel,
    chapter: Any,
    workflow_run_id: str,
    memory_context: str,
) -> dict[str, Any]:
    outline = novel.total_outline
    total_outline = (
        outline.__dict__
        if outline and hasattr(outline, "__dict__")
        else (outline if isinstance(outline, dict) else {})
    )
    return {
        "novel_type": novel.novel_type,
        "title": novel.title or "",
        "summary": novel.summary or "",
        "current_chapter_index": chapter.chapter_index,
        "chapter_outlines": [chapter.outline or {}],
        "total_outline": total_outline,
        "memory_context": memory_context,
        "current_chapter_content": "",
        "workflow_run_id": workflow_run_id,
    }


async def _generate_rewritten_chapter(
    state: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    await _run_rewrite_node("chapter_writer_node", state, config)
    if not state.get("current_chapter_content"):
        raise HTTPException(status_code=500, detail="章节内容生成失败")

    node_name = "reflection_node"
    for _ in range(REWRITE_MAX_NODE_STEPS):
        try:
            goto = await _run_rewrite_node(node_name, state, config)
        except QualityGateReviewRequired as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "quality_gate_not_met", "message": str(exc)},
            ) from exc
        if node_name == "persist_node":
            return state
        allowed = {
            "reflection_node": {"persist_node", "revision_node"},
            "revision_node": {"reflection_node"},
        }
        if goto not in allowed[node_name]:
            raise HTTPException(status_code=500, detail="章节重写流程返回了无效状态")
        node_name = goto
    raise HTTPException(status_code=500, detail="章节重写超过最大修订次数")


async def _run_rewrite_node(
    node_name: str, state: dict[str, Any], config: dict[str, Any]
) -> str:
    from application.agents.chapter_writer_node import chapter_writer_node
    from application.agents.persist_node import persist_node
    from application.agents.reflection_node import reflection_node
    from application.agents.revision_node import revision_node

    nodes = {
        "chapter_writer_node": chapter_writer_node,
        "reflection_node": reflection_node,
        "revision_node": revision_node,
        "persist_node": persist_node,
    }
    node = nodes.get(node_name)
    if node is None:
        raise HTTPException(status_code=500, detail="章节重写流程节点不存在")
    command = await node(state, config)
    state.update(command.update or {})
    if not isinstance(command.goto, str):
        raise HTTPException(status_code=500, detail="章节重写流程返回了无效路由")
    return command.goto


async def _load_rewrite_target(
    repo: PostgresNovelRepository,
    context: TenantContext,
    novel_id: str,
    chapter_id: str,
) -> tuple[Any, Novel]:
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if chapter is None or str(chapter.novel_id) != novel_id or novel is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not chapter.outline:
        raise HTTPException(status_code=400, detail="该章节没有细纲数据，无法重写")
    return chapter, novel


async def _reserve_rewrite(
    quota: QuotaService,
    context: TenantContext,
    workflow_run_id: UUID,
    chapter_index: int,
) -> None:
    try:
        await quota.reserve(context, workflow_run_id, "rewrite", chapter_index)
    except (QuotaExceededError, AIUnavailableError) as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "quota_exceeded", "message": str(exc)},
        ) from exc


async def _finish_rewrite(
    repo: PostgresNovelRepository,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    novel_id: str,
    state: dict[str, Any],
) -> ChapterDetailResponse:
    completed = state.get("completed_chapters", [])
    persisted_id = completed[-1].get("id") if completed else None
    persisted = (
        await repo.find_chapter_by_id(_tenant_id(context), persisted_id)
        if persisted_id
        else None
    )
    if persisted is None:
        raise HTTPException(status_code=500, detail="重写章节保存失败")
    checkpoint_status = await reconcile_pending_checkpoint(
        repo, orchestrator, context, novel_id
    )
    return _chapter_response(persisted, checkpoint_status)


@router.post(
    "/{novel_id}/chapters/{chapter_id}/rewrite",
    response_model=ChapterDetailResponse,
)
async def rewrite_chapter(
    novel_id: str,
    chapter_id: str,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    quota: QuotaService = request.app.state.quota_service
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    try:
        async with orchestrator.exclusive_operation(context, novel_id, "正在重写章节"):
            chapter, novel = await _load_rewrite_target(
                repo, context, novel_id, chapter_id
            )
            workflow_run_id = uuid4()
            await _reserve_rewrite(
                quota, context, workflow_run_id, chapter.chapter_index
            )
            config = _rewrite_config(
                request, context, novel_id, repo, quota, orchestrator
            )
            memory_context = (
                await request.app.state.memory_service.get_hierarchical_context(
                    _tenant_id(context), novel_id, chapter.chapter_index
                )
            )
            state = await _generate_rewritten_chapter(
                _rewrite_state(
                    novel,
                    chapter,
                    str(workflow_run_id),
                    memory_context,
                ),
                config,
            )
            return await _finish_rewrite(
                repo,
                orchestrator,
                context,
                novel_id,
                state,
            )
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if not context.can_delete_content():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    await repo.delete(_tenant_id(context), novel_id)
    return {"status": "deleted", "novel_id": novel_id}


@router.post("/{novel_id}/chapters/batch-delete")
async def batch_delete_chapters(
    novel_id: str,
    payload: ChapterBatchDeleteRequest,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if not context.can_delete_content():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    try:
        async with orchestrator.exclusive_operation(context, novel_id, "正在回退章节"):
            deleted, rewind_to = await repo.rewind_chapters_atomically(
                _tenant_id(context), novel_id, payload.chapter_ids
            )
            if rewind_to is None:
                raise HTTPException(status_code=404, detail="未找到可回退的章节")
            checkpoint_status = await reconcile_pending_checkpoint(
                repo, orchestrator, context, novel_id
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="章节 ID 格式不正确") from exc
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc
    return {
        "status": "rewound",
        "count": deleted,
        "rewind_to": rewind_to,
        "checkpoint_status": checkpoint_status,
    }
