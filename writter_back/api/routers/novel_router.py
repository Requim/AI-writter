"""Tenant-scoped novel, chapter and rewrite endpoints."""

from datetime import datetime
import logging
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from api.dependencies import get_tenant_context
from application.quota_service import QuotaService
from infrastructure.database.identity_repository import AIUnavailableError, QuotaExceededError
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress

logger = logging.getLogger("uvicorn")
router = APIRouter()


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


class ChapterUpdateRequest(BaseModel):
    title: str
    content: str


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
    return {"novel_id": str(saved.id), "thread_id": novel.thread_id, "status": "created"}


@router.get("", response_model=list[NovelResponse])
async def list_novels(
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    return [_novel_response(novel) for novel in await repo.find_all(_tenant_id(context))]


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
        )
        for chapter in novel.chapters
    ]


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_chapter(
    novel_id: str,
    chapter_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    if chapter is None or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {
        "id": str(chapter.id),
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "content": chapter.content,
        "word_count": chapter.word_count,
        "status": chapter.status,
    }


@router.put("/{novel_id}/chapters/{chapter_id}")
async def update_chapter(
    novel_id: str,
    chapter_id: str,
    payload: ChapterUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    if chapter is None or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    chapter.title = payload.title.strip() or chapter.title
    chapter.content = payload.content
    chapter.word_count = len(payload.content)
    chapter.updated_at = datetime.now()
    await repo.update_chapter(_tenant_id(context), chapter)
    return {
        "id": str(chapter.id),
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "content": chapter.content,
        "word_count": chapter.word_count,
        "status": chapter.status,
    }


@router.post("/{novel_id}/chapters/{chapter_id}/rewrite")
async def rewrite_chapter(
    novel_id: str,
    chapter_id: str,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    from application.agents.chapter_writer_node import chapter_writer_node
    from application.agents.persist_node import persist_node
    from application.agents.reflection_node import reflection_node
    from application.agents.revision_node import revision_node

    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    if chapter is None or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    chapter_outline = chapter.outline or {}
    if not chapter_outline:
        raise HTTPException(status_code=400, detail="该章节没有细纲数据，无法重写")

    workflow_run_id = uuid4()
    quota: QuotaService = request.app.state.quota_service
    try:
        await quota.reserve(context, workflow_run_id, "rewrite", chapter.chapter_index)
    except (QuotaExceededError, AIUnavailableError) as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "quota_exceeded", "message": str(exc)},
        ) from exc

    orchestrator = request.app.state.orchestrator
    cfg = {
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
            "llm_config": {"llm_instance": orchestrator._get_llm_instance()},
        }
    }
    outline = novel.total_outline
    total_outline = (
        outline.__dict__
        if outline and hasattr(outline, "__dict__")
        else (outline if isinstance(outline, dict) else {})
    )
    state = {
        "novel_type": novel.novel_type,
        "title": novel.title or "",
        "summary": novel.summary or "",
        "current_chapter_index": chapter.chapter_index,
        "chapter_outlines": [chapter_outline],
        "total_outline": total_outline,
        "memory_context": "",
        "current_chapter_content": "",
        "_skip_interrupt": True,
        "workflow_run_id": str(workflow_run_id),
    }
    command = await chapter_writer_node(state, cfg)
    if command.update:
        state.update(command.update)
    if not state.get("current_chapter_content"):
        raise HTTPException(status_code=500, detail="章节内容生成失败")
    command = await reflection_node(state, cfg)
    if command.update:
        state.update(command.update)
    if command.goto == "revision_node":
        command = await revision_node(state, cfg)
        if command.update:
            state.update(command.update)
    rewritten_content = state.get("current_chapter_content", "")
    command = await persist_node(state, cfg)
    if command.update:
        state.update(command.update)
    return {
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "content": rewritten_content,
        "word_count": len(rewritten_content),
        "status": "completed",
    }


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
    payload: dict[str, Any],
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if not context.can_delete_content():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    chapter_ids = payload.get("chapter_ids", [])
    if not chapter_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的章节")
    try:
        deleted, rewind_to = await repo.delete_chapters_atomically(
            _tenant_id(context), novel_id, chapter_ids
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="章节 ID 格式不正确") from exc
    return {"status": "deleted", "count": deleted, "rewind_to": rewind_to}
