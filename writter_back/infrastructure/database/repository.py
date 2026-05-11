"""小说仓储实现"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, update, delete
from typing import Optional, List
import uuid

from service.entities.novel import Novel
from service.entities.chapter import Chapter
from service.ports.novel_repository import NovelRepository
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from .models import Base, NovelModel, ChapterModel


class PostgresNovelRepository(NovelRepository):
    """PostgreSQL小说仓储实现"""

    def __init__(self, database_url: str):
        self.engine = create_async_engine(database_url)
        self.async_session = async_sessionmaker(self.engine, class_=AsyncSession)

    async def init_db(self):
        """初始化数据库（创建表）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def save(self, novel: Novel) -> Novel:
        """保存小说"""
        async with self.async_session() as session:
            novel_model = NovelModel(
                id=novel.id,
                user_id=novel.user_id,
                novel_type=novel.novel_type,
                title=novel.title,
                summary=novel.summary,
                total_outline=novel.total_outline.__dict__ if novel.total_outline else None,
                progress=novel.progress.to_dict() if novel.progress else None,
                status=novel.progress.status if novel.progress else "draft",
                thread_id=novel.thread_id,
                created_at=novel.created_at,
                updated_at=novel.updated_at
            )
            session.add(novel_model)
            await session.commit()
            return novel

    async def find_by_id(self, novel_id: str) -> Optional[Novel]:
        """根据ID查找"""
        async with self.async_session() as session:
            stmt = select(NovelModel).where(NovelModel.id == uuid.UUID(novel_id))
            result = await session.execute(stmt)
            novel_model = result.scalar_one_or_none()

            if not novel_model:
                return None

            outline = Outline(**novel_model.total_outline) if novel_model.total_outline else None
            progress = Progress(**novel_model.progress) if novel_model.progress else Progress()

            return Novel(
                id=novel_model.id,
                user_id=novel_model.user_id,
                novel_type=novel_model.novel_type,
                title=novel_model.title,
                summary=novel_model.summary,
                total_outline=outline,
                progress=progress,
                thread_id=novel_model.thread_id,
                created_at=novel_model.created_at,
                updated_at=novel_model.updated_at
            )

    async def find_by_id_with_chapters(self, novel_id: str) -> Optional[Novel]:
        """根据ID查找小说及其所有章节"""
        async with self.async_session() as session:
            stmt = select(NovelModel).where(NovelModel.id == uuid.UUID(novel_id))
            result = await session.execute(stmt)
            novel_model = result.scalar_one_or_none()

            if not novel_model:
                return None

            outline = Outline(**novel_model.total_outline) if novel_model.total_outline else None
            progress = Progress(**novel_model.progress) if novel_model.progress else Progress()

            novel = Novel(
                id=novel_model.id,
                user_id=novel_model.user_id,
                novel_type=novel_model.novel_type,
                title=novel_model.title,
                summary=novel_model.summary,
                total_outline=outline,
                progress=progress,
                thread_id=novel_model.thread_id,
                created_at=novel_model.created_at,
                updated_at=novel_model.updated_at
            )

            # 加载章节
            chapters_stmt = select(ChapterModel).where(
                ChapterModel.novel_id == uuid.UUID(novel_id)
            ).order_by(ChapterModel.chapter_index)
            chapters_result = await session.execute(chapters_stmt)
            chapter_models = chapters_result.scalars().all()

            for cm in chapter_models:
                chapter = Chapter(
                    id=cm.id,
                    novel_id=cm.novel_id,
                    chapter_index=cm.chapter_index,
                    title=cm.title,
                    outline=cm.outline,
                    content=cm.content,
                    word_count=cm.word_count,
                    reflection_issues=cm.reflection_issues or [],
                    user_decision=cm.user_decision,
                    revision_count=cm.revision_count,
                    revision_history=cm.revision_history or [],
                    status=cm.status,
                    created_at=cm.created_at,
                    updated_at=cm.updated_at
                )
                novel.add_chapter(chapter)

            return novel

    async def find_all_by_user(self, user_id: str) -> List[Novel]:
        """查找用户所有小说（user_id 为空时返回所有）"""
        async with self.async_session() as session:
            stmt = select(NovelModel)
            if user_id:
                stmt = stmt.where(NovelModel.user_id == uuid.UUID(user_id))
            result = await session.execute(stmt)
            novels = result.scalars().all()
            return [
                Novel(
                    id=n.id,
                    user_id=n.user_id,
                    novel_type=n.novel_type,
                    title=n.title,
                    summary=n.summary,
                    total_outline=Outline(**n.total_outline) if n.total_outline else None,
                    progress=Progress(**n.progress) if n.progress else Progress(),
                    thread_id=n.thread_id,
                    created_at=n.created_at,
                    updated_at=n.updated_at,
                )
                for n in novels
            ]

    async def update(self, novel: Novel) -> Novel:
        """更新小说"""
        async with self.async_session() as session:
            stmt = (
                update(NovelModel)
                .where(NovelModel.id == novel.id)
                .values(
                    title=novel.title,
                    summary=novel.summary,
                    total_outline=novel.total_outline.__dict__ if novel.total_outline else None,
                    progress=novel.progress.to_dict() if novel.progress else None,
                    status=novel.progress.status if novel.progress else "draft",
                    updated_at=novel.updated_at
                )
            )
            await session.execute(stmt)
            await session.commit()
            return novel

    async def delete(self, novel_id: str) -> None:
        """删除小说"""
        async with self.async_session() as session:
            stmt = delete(NovelModel).where(NovelModel.id == uuid.UUID(novel_id))
            await session.execute(stmt)
            await session.commit()

    async def delete_chapter(self, chapter_id: str) -> None:
        """删除单个章节"""
        from .models import ChapterModel
        async with self.async_session() as session:
            stmt = delete(ChapterModel).where(ChapterModel.id == uuid.UUID(chapter_id))
            await session.execute(stmt)
            await session.commit()

    async def delete_chapters_by_index(self, novel_id: str, chapter_index: int) -> None:
        """删除指定小说和章节索引的所有旧版本章节（upsert 用）"""
        from .models import ChapterModel
        async with self.async_session() as session:
            stmt = (
                delete(ChapterModel)
                .where(ChapterModel.novel_id == uuid.UUID(novel_id))
                .where(ChapterModel.chapter_index == chapter_index)
            )
            await session.execute(stmt)
            await session.commit()

    # --- Chapter operations ---

    async def save_chapter(self, novel_id: str, chapter: Chapter) -> Chapter:
        """保存章节"""
        async with self.async_session() as session:
            chapter_model = ChapterModel(
                id=chapter.id,
                novel_id=uuid.UUID(novel_id),
                chapter_index=chapter.chapter_index,
                title=chapter.title,
                outline=chapter.outline,
                content=chapter.content,
                word_count=chapter.word_count,
                reflection_issues=chapter.reflection_issues or None,
                user_decision=chapter.user_decision,
                revision_count=chapter.revision_count,
                revision_history=chapter.revision_history or None,
                status=chapter.status,
                created_at=chapter.created_at,
                updated_at=chapter.updated_at
            )
            session.add(chapter_model)
            await session.commit()
            return chapter

    async def find_chapter_by_id(self, chapter_id: str) -> Optional[Chapter]:
        """根据ID查找章节"""
        async with self.async_session() as session:
            stmt = select(ChapterModel).where(ChapterModel.id == uuid.UUID(chapter_id))
            result = await session.execute(stmt)
            cm = result.scalar_one_or_none()

            if not cm:
                return None

            return Chapter(
                id=cm.id,
                novel_id=cm.novel_id,
                chapter_index=cm.chapter_index,
                title=cm.title,
                outline=cm.outline,
                content=cm.content,
                word_count=cm.word_count,
                reflection_issues=cm.reflection_issues or [],
                user_decision=cm.user_decision,
                revision_count=cm.revision_count,
                revision_history=cm.revision_history or [],
                status=cm.status,
                created_at=cm.created_at,
                updated_at=cm.updated_at
            )

    async def update_chapter(self, chapter: Chapter) -> Chapter:
        """更新章节"""
        async with self.async_session() as session:
            stmt = (
                update(ChapterModel)
                .where(ChapterModel.id == chapter.id)
                .values(
                    title=chapter.title,
                    outline=chapter.outline,
                    content=chapter.content,
                    word_count=chapter.word_count,
                    reflection_issues=chapter.reflection_issues or None,
                    user_decision=chapter.user_decision,
                    revision_count=chapter.revision_count,
                    revision_history=chapter.revision_history or None,
                    status=chapter.status,
                    updated_at=chapter.updated_at
                )
            )
            await session.execute(stmt)
            await session.commit()
            return chapter
