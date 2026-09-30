"""章节归档事务中的自主后处理标记，禁止恢复时覆盖已存在正文。"""

from sqlalchemy import select

from application.creative.errors import CreativeConflict
from application.creative.evidence import content_hash
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.models import ChapterModel


async def guard_creative_archive(session, tenant_id, novel_id, chapter):
    """已归档的新模式章节不能由同一次生成恢复覆盖，内容一致则复用。"""
    creative = await session.scalar(select(CreativeSessionModel).where(
        CreativeSessionModel.tenant_id == tenant_id, CreativeSessionModel.novel_id == novel_id,
    ))
    if creative is None:
        return False
    existing = await session.scalar(select(ChapterModel).where(
        ChapterModel.tenant_id == tenant_id, ChapterModel.novel_id == novel_id,
        ChapterModel.chapter_index == chapter.chapter_index,
    ))
    if existing is not None:
        if str(existing.id) != str(chapter.id) or content_hash(existing.content or "") != content_hash(chapter.content or ""):
            raise CreativeConflict("归档正文已存在，自主恢复不得重写历史章节")
        return True
    creative.stage = f"postprocess:{chapter.chapter_index + 1}"
    creative.status = "pending"
    return False
