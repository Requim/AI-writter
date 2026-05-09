"""小说路由 - 接入 PostgresNovelRepository"""
import logging
logger = logging.getLogger("uvicorn")
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
    total_outline: Optional[dict] = None


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
        logger.info(f"[create_novel] request body: {request.model_dump()}")
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
        logger.info(f"[create_novel] novel created: {saved.id}")

        return {
            "novel_id": str(saved.id),
            "thread_id": novel.thread_id,
            "status": "created",
        }
    except Exception as e:
        logger.info(f"[create_novel] error: {e}")
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
            total_outline=n.total_outline.__dict__ if n.total_outline and hasattr(n.total_outline, '__dict__') else (n.total_outline if isinstance(n.total_outline, dict) else None),
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
        total_outline=novel.total_outline.__dict__ if novel.total_outline and hasattr(novel.total_outline, '__dict__') else (novel.total_outline if isinstance(novel.total_outline, dict) else None),
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


@router.post("/{novel_id}/chapters/{chapter_id}/rewrite")
async def rewrite_chapter(
    novel_id: str,
    chapter_id: str,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """重写指定章节——走完整链路：写作 → 反思(LLM检查) → 修正(LLM修正) → 持久化"""
    from config import settings
    from infrastructure.llm import DeepSeekAdapter, OpenAIAdapter, AnthropicAdapter
    from application.agents.chapter_writer_node import chapter_writer_node
    from application.agents.reflection_node import reflection_node
    from application.agents.revision_node import revision_node
    from application.agents.persist_node import persist_node

    # 1. 加载章节和小说信息
    chapter = await repo.find_chapter_by_id(chapter_id)
    if not chapter or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")

    novel = await repo.find_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    chapter_outline = chapter.outline or {}
    if not chapter_outline:
        raise HTTPException(status_code=400, detail="该章节没有细纲数据，无法重写")

    # 2. 创建 LLM 实例 + 构造 config
    provider = settings.DEFAULT_LLM_PROVIDER
    model = settings.DEFAULT_MODEL_NAME
    if provider == "openai":
        llm = OpenAIAdapter(api_key=settings.OPENAI_API_KEY, model=model)
    elif provider == "anthropic":
        llm = AnthropicAdapter(api_key=settings.ANTHROPIC_API_KEY, model=model)
    else:
        llm = DeepSeekAdapter(api_key=settings.DEEPSEEK_API_KEY, model=model)

    cfg = {
        "configurable": {
            "thread_id": novel_id,
            "novel_repository": repo,
            "llm_config": {"llm_instance": llm},
        }
    }

    # 3. 构建初始 state
    total_outline = {}
    if novel.total_outline:
        if hasattr(novel.total_outline, '__dict__'):
            total_outline = novel.total_outline.__dict__
        elif isinstance(novel.total_outline, dict):
            total_outline = novel.total_outline

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
    }

    # ====== 链路 1：章节写作 ======
    logger.info(f"【重写】开始写作 | 章节={chapter.chapter_index}, 细纲标题={chapter_outline.get('title','')}")
    cmd = await chapter_writer_node(state, cfg)
    if cmd.update:
        state.update(cmd.update)

    if not state.get("current_chapter_content"):
        raise HTTPException(status_code=500, detail="章节内容生成失败")

    # ====== 链路 2：反思检查（LLM 检查 + 自动修正） ======
    logger.info(f"【重写】开始反思质检 | 内容长度={len(state['current_chapter_content'])}")
    cmd = await reflection_node(state, cfg)
    if cmd.update:
        state.update(cmd.update)

    # ====== 链路 3：修正（如果反思发现问题） ======
    if cmd.goto == "revision_node":
        logger.info(f"【重写】反思发现问题，开始自动修正")
        cmd = await revision_node(state, cfg)
        if cmd.update:
            state.update(cmd.update)

    # ====== 链路 4：先删旧章节，再持久化新章节 ======
    logger.info(f"【重写】保存新章节")
    try:
        await repo.delete_chapter(chapter_id)
    except Exception:
        pass
    cmd = await persist_node(state, cfg)
    if cmd.update:
        state.update(cmd.update)

    return {
        "chapter_index": chapter.chapter_index,
        "title": chapter.title,
        "content": state.get("current_chapter_content", ""),
        "word_count": len(state.get("current_chapter_content", "") or ""),
        "status": "completed",
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


@router.post("/{novel_id}/chapters/batch-delete")
async def batch_delete_chapters(
    novel_id: str,
    request: dict,
    repo: PostgresNovelRepository = Depends(get_repository),
):
    """批量删除章节（含记忆和 checkpointer 数据），并回退 current_chapter_index"""
    from sqlalchemy import text as sql_text

    chapter_ids = request.get("chapter_ids", [])
    if not chapter_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的章节")
    deleted = 0
    min_index = None

    async with repo.async_session() as session:
        for cid in chapter_ids:
            try:
                ch = await repo.find_chapter_by_id(cid)
                if ch:
                    idx = ch.chapter_index
                    if min_index is None or idx < min_index:
                        min_index = idx
                    # 删 novel_memories 中该章节的记忆（按 chapter_index 匹配）
                    try:
                        await session.execute(
                            sql_text("DELETE FROM novel_memories WHERE novel_id = :nid AND content LIKE :pat"),
                            {"nid": uuid.UUID(novel_id), "pat": f"%第{idx + 1}章%"}
                        )
                    except Exception:
                        pass
                await repo.delete_chapter(cid)
                deleted += 1
            except Exception:
                pass

        await session.commit()

    # 回退 current_chapter_index
    if min_index is not None:
        try:
            novel = await repo.find_by_id(novel_id)
            if novel and novel.progress:
                old_progress = novel.progress.to_dict() if hasattr(novel.progress, 'to_dict') else {}
                if old_progress.get("current_chapter", 0) > min_index:
                    old_progress["current_chapter"] = min_index
                    new_total = max(1, old_progress.get("total_chapters", 1) - deleted)
                    old_progress["total_chapters"] = new_total
                    from service.value_objects.progress import Progress
                    novel.progress = Progress(**old_progress)
                    await repo.update(novel)
        except Exception:
            pass

    return {"status": "deleted", "count": deleted}
