"""小说路由 - 接入 PostgresNovelRepository"""
from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from uuid import uuid4, UUID
from datetime import datetime

from service.entities.novel import Novel
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from infrastructure.database.repository import PostgresNovelRepository
from config import settings

router = APIRouter()


# ---------- Dependency Injection ----------
def get_repository() -> PostgresNovelRepository:
    return PostgresNovelRepository(settings.DATABASE_URL)


# ---------- Request / Response Schemas ----------
class NovelCreateRequest(BaseModel):
    novel_type: str
    title: Optional[str] = None
    summary: Optional[str] = None
    total_outline: Optional[dict] = None


class NovelResponse(BaseModel):
    id: str
    novel_type: str
    title: Optional[str]
    summary: Optional[str]
    status: str
    progress_percentage: float = 0.0
    thread_id: Optional[str] = None


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


# ---------- Endpoints ----------
@router.post("", response_model=dict)
async def create_novel(
    request: NovelCreateRequest,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """创建小说（启动创作流程）"""
    try:
        print(f"[create_novel] request body: {request.model_dump()}", flush=True)
        # 验证 novel_type
        try:
            valid_type = NovelType(request.novel_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的小说类型: {request.novel_type}")

        outline = Outline(**request.total_outline) if request.total_outline else None
        progress = Progress()  # 初始进度：0/0

        novel_id = uuid4()
        novel = Novel(
            id=novel_id,
            user_id=None,  # TODO: 从 JWT 中获取 user_id
            novel_type=valid_type.value,
            title=request.title,
            summary=request.summary,
            total_outline=outline,
            progress=progress,
            thread_id=str(novel_id),  # thread_id = novel_id
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        saved = await repo.save(novel)
        print(f"[create_novel] novel created: {saved.id}", flush=True)

        return {
            "novel_id": str(saved.id),
            "thread_id": novel.thread_id,
            "status": "created",
        }
    except Exception as e:
        print(f"[create_novel] error: {e}", flush=True)
        raise


@router.get("", response_model=List[NovelResponse])
async def list_novels(
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """获取所有小说"""
    novels = await repo.find_all_by_user("")  # TODO: 从 JWT 获取 user_id
    return [
        NovelResponse(
            id=str(n.id),
            novel_type=n.novel_type,
            title=n.title,
            summary=n.summary,
            status=n.progress.status if n.progress else "draft",
            progress_percentage=n.progress.percentage if n.progress else 0.0,
            thread_id=n.thread_id,
        )
        for n in novels
    ]


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(
    novel_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """获取小说详情"""
    novel = await repo.find_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return NovelResponse(
        id=str(novel.id),
        novel_type=novel.novel_type,
        title=novel.title,
        summary=novel.summary,
        status=novel.progress.status if novel.progress else "draft",
        progress_percentage=novel.progress.percentage if novel.progress else 0.0,
        thread_id=novel.thread_id,
    )


@router.get("/{novel_id}/progress", response_model=ProgressResponse)
async def get_progress(
    novel_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """获取小说进度"""
    novel = await repo.find_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    progress = novel.progress if novel.progress else Progress()
    return ProgressResponse(
        current_chapter=progress.current_chapter,
        total_chapters=progress.total_chapters,
        percentage=progress.percentage,
        status=progress.status,
    )


@router.get("/{novel_id}/chapters", response_model=List[ChapterResponse])
async def list_chapters(
    novel_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """获取所有章节"""
    novel = await repo.find_by_id_with_chapters(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return [
        ChapterResponse(
            id=str(ch.id),
            chapter_index=ch.chapter_index,
            title=ch.title,
            word_count=ch.word_count,
            status=ch.status,
        )
        for ch in novel.chapters
    ]


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_chapter(
    novel_id: str,
    chapter_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """获取单个章节详情（含完整内容）"""
    from uuid import UUID
    chapter = await repo.find_chapter_by_id(chapter_id)
    if not chapter or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    return {
        "id": str(chapter.id),
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "content": chapter.content,
        "word_count": chapter.word_count,
        "status": chapter.status,
    }


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """删除小说及其所有章节"""
    novel = await repo.find_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    await repo.delete(novel_id)
    return {"status": "deleted", "novel_id": novel_id}
