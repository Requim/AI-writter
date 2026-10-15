"""Authenticated downloads of archived manuscripts, without changing prose."""

import re
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.dependencies import get_tenant_context
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext

router = APIRouter()


def get_repository(request: Request) -> PostgresNovelRepository:
    return request.app.state.repository


@router.get("/{novel_id}/export")
async def export_manuscript(
    novel_id: str,
    format: Literal["txt", "md"] = "txt",
    context: TenantContext = Depends(get_tenant_context),
    repository: PostgresNovelRepository = Depends(get_repository),
) -> Response:
    try:
        novel = await repository.find_by_id_with_chapters(str(context.tenant_id), novel_id)
    except ValueError:
        novel = None
    if novel is None:
        raise HTTPException(404, detail="小说不存在")
    chapters = sorted(
        (chapter for chapter in novel.chapters if chapter.status == "completed"),
        key=lambda chapter: chapter.chapter_index,
    )
    if not chapters:
        raise HTTPException(409, detail={"code": "no_archived_chapters", "message": "暂无已归档章节"})
    title = novel.title or "未命名作品"
    parts = [f"# {title}" if format == "md" else title]
    if novel.summary:
        parts.append(novel.summary)
    for chapter in chapters:
        heading = chapter.title or f"第{chapter.chapter_index + 1}章"
        parts.extend([f"## {heading}" if format == "md" else heading, chapter.content])
    filename = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", title).strip(". ")[:100] or "manuscript"
    body = "\ufeff" + "\n\n".join(parts) + "\n"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/markdown" if format == "md" else "text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=\"manuscript.{format}\"; filename*=UTF-8''{quote(filename)}.{format}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
