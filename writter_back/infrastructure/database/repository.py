"""小说仓储实现"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import delete, select, text, update
from typing import Optional, List
import uuid

from service.entities.novel import Novel
from service.entities.chapter import Chapter
from service.ports.novel_repository import NovelRepository
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from .models import Base, ChapterModel, MemoryModel, NovelModel


class PostgresNovelRepository(NovelRepository):
    """PostgreSQL小说仓储实现"""

    def __init__(
        self,
        database_url: str,
        pool_size: int = 10,
        max_overflow: int = 20,
    ):
        self.engine = create_async_engine(
            database_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self):
        """初始化数据库（创建表）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def aclose(self) -> None:
        await self.engine.dispose()

    async def save(self, tenant_id: str, novel: Novel) -> Novel:
        """保存小说"""
        async with self.async_session() as session:
            novel_model = NovelModel(
                id=novel.id,
                tenant_id=uuid.UUID(tenant_id),
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

    async def find_by_id(self, tenant_id: str, novel_id: str) -> Optional[Novel]:
        """根据ID查找"""
        async with self.async_session() as session:
            stmt = select(NovelModel).where(
                NovelModel.tenant_id == uuid.UUID(tenant_id),
                NovelModel.id == uuid.UUID(novel_id),
            )
            result = await session.execute(stmt)
            novel_model = result.scalar_one_or_none()

            if not novel_model:
                return None

            outline = Outline(**novel_model.total_outline) if novel_model.total_outline else None
            progress = Progress(**novel_model.progress) if novel_model.progress else Progress()

            return Novel(
                id=novel_model.id,
                tenant_id=novel_model.tenant_id,
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

    async def find_by_id_with_chapters(self, tenant_id: str, novel_id: str) -> Optional[Novel]:
        """根据ID查找小说及其所有章节"""
        async with self.async_session() as session:
            tenant_uuid = uuid.UUID(tenant_id)
            stmt = select(NovelModel).where(
                NovelModel.tenant_id == tenant_uuid,
                NovelModel.id == uuid.UUID(novel_id),
            )
            result = await session.execute(stmt)
            novel_model = result.scalar_one_or_none()

            if not novel_model:
                return None

            outline = Outline(**novel_model.total_outline) if novel_model.total_outline else None
            progress = Progress(**novel_model.progress) if novel_model.progress else Progress()

            novel = Novel(
                id=novel_model.id,
                tenant_id=novel_model.tenant_id,
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
                ChapterModel.tenant_id == tenant_uuid,
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

    async def find_all(self, tenant_id: str) -> List[Novel]:
        """查找租户所有小说。"""
        async with self.async_session() as session:
            stmt = (
                select(NovelModel)
                .where(NovelModel.tenant_id == uuid.UUID(tenant_id))
                .order_by(NovelModel.updated_at.desc())
            )
            result = await session.execute(stmt)
            novels = result.scalars().all()
            return [
                Novel(
                    id=n.id,
                    tenant_id=n.tenant_id,
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

    async def update(self, tenant_id: str, novel: Novel) -> Novel:
        """更新小说"""
        async with self.async_session() as session:
            stmt = (
                update(NovelModel)
                .where(
                    NovelModel.tenant_id == uuid.UUID(tenant_id),
                    NovelModel.id == novel.id,
                )
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

    async def delete(self, tenant_id: str, novel_id: str) -> None:
        """删除小说"""
        async with self.async_session() as session:
            stmt = delete(NovelModel).where(
                NovelModel.tenant_id == uuid.UUID(tenant_id),
                NovelModel.id == uuid.UUID(novel_id),
            )
            await session.execute(stmt)
            await session.commit()

    async def delete_chapter(self, tenant_id: str, chapter_id: str) -> None:
        """删除单个章节"""
        from .models import ChapterModel
        async with self.async_session() as session:
            stmt = delete(ChapterModel).where(
                ChapterModel.tenant_id == uuid.UUID(tenant_id),
                ChapterModel.id == uuid.UUID(chapter_id),
            )
            await session.execute(stmt)
            await session.commit()

    async def delete_chapters_by_index(
        self, tenant_id: str, novel_id: str, chapter_index: int
    ) -> None:
        """删除指定小说和章节索引的所有旧版本章节（upsert 用）"""
        from .models import ChapterModel
        async with self.async_session() as session:
            stmt = (
                delete(ChapterModel)
                .where(ChapterModel.tenant_id == uuid.UUID(tenant_id))
                .where(ChapterModel.novel_id == uuid.UUID(novel_id))
                .where(ChapterModel.chapter_index == chapter_index)
            )
            await session.execute(stmt)
            await session.commit()

    # --- Chapter operations ---

    async def save_chapter(
        self, tenant_id: str, novel_id: str, chapter: Chapter
    ) -> Chapter:
        """保存章节"""
        async with self.async_session() as session:
            chapter_model = ChapterModel(
                id=chapter.id,
                tenant_id=uuid.UUID(tenant_id),
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

    async def replace_chapter(
        self,
        tenant_id: str,
        novel_id: str,
        chapter: Chapter,
        memory_content: str,
        memory_metadata: dict,
        progress: Progress,
    ) -> Chapter:
        """Atomically replace a chapter, its M-layer memory and novel progress."""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            await session.execute(
                delete(ChapterModel).where(
                    ChapterModel.tenant_id == tenant_uuid,
                    ChapterModel.novel_id == novel_uuid,
                    ChapterModel.chapter_index == chapter.chapter_index,
                )
            )
            await session.execute(
                text(
                    "DELETE FROM novel_memories "
                    "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
                    "AND metadata @> CAST(:metadata AS jsonb)"
                ),
                {
                    "novel_id": novel_uuid,
                    "tenant_id": tenant_uuid,
                    "metadata": '{"type":"chapter","chapter_index":%d}'
                    % chapter.chapter_index,
                },
            )
            session.add(
                ChapterModel(
                    id=chapter.id,
                    tenant_id=tenant_uuid,
                    novel_id=novel_uuid,
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
                    updated_at=chapter.updated_at,
                )
            )
            session.add(
                MemoryModel(
                    tenant_id=tenant_uuid,
                    novel_id=novel_uuid,
                    content=memory_content,
                    meta_data=memory_metadata,
                )
            )
            await session.execute(
                update(NovelModel)
                .where(
                    NovelModel.tenant_id == tenant_uuid,
                    NovelModel.id == novel_uuid,
                )
                .values(
                    progress=progress.to_dict(),
                    status=progress.status,
                    updated_at=chapter.updated_at,
                )
            )
        return chapter

    async def delete_chapters_atomically(
        self, tenant_id: str, novel_id: str, chapter_ids: list[str]
    ) -> tuple[int, int | None]:
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        ids = [uuid.UUID(chapter_id) for chapter_id in chapter_ids]
        async with self.async_session() as session, session.begin():
            rows = (
                await session.execute(
                    select(ChapterModel.id, ChapterModel.chapter_index).where(
                        ChapterModel.tenant_id == tenant_uuid,
                        ChapterModel.novel_id == novel_uuid,
                        ChapterModel.id.in_(ids),
                    )
                )
            ).all()
            if not rows:
                return 0, None
            indexes = sorted({row.chapter_index for row in rows})
            for index in indexes:
                await session.execute(
                    text(
                        "DELETE FROM novel_memories "
                        "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
                        "AND metadata @> CAST(:metadata AS jsonb)"
                    ),
                    {
                        "novel_id": novel_uuid,
                        "tenant_id": tenant_uuid,
                        "metadata": '{"chapter_index":%d}' % index,
                    },
                )
            await session.execute(
                delete(ChapterModel).where(
                    ChapterModel.tenant_id == tenant_uuid,
                    ChapterModel.novel_id == novel_uuid,
                    ChapterModel.id.in_([row.id for row in rows]),
                )
            )
            novel = (
                await session.execute(
                    select(NovelModel).where(
                        NovelModel.tenant_id == tenant_uuid,
                        NovelModel.id == novel_uuid,
                    )
                )
            ).scalar_one_or_none()
            min_index = indexes[0]
            if novel is not None:
                progress_data = dict(novel.progress or {})
                total = int(progress_data.get("total_chapters", 0) or 0)
                current = min(int(progress_data.get("current_chapter", 0) or 0), min_index)
                progress_data.update(
                    {
                        "current_chapter": current,
                        "percentage": (current / total * 100) if total else 0,
                        "status": "writing" if current else "draft",
                    }
                )
                novel.progress = progress_data
                novel.status = progress_data["status"]
        return len(rows), indexes[0]

    async def find_chapter_by_id(
        self, tenant_id: str, chapter_id: str
    ) -> Optional[Chapter]:
        """根据ID查找章节"""
        async with self.async_session() as session:
            stmt = select(ChapterModel).where(
                ChapterModel.tenant_id == uuid.UUID(tenant_id),
                ChapterModel.id == uuid.UUID(chapter_id),
            )
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

    async def update_chapter(self, tenant_id: str, chapter: Chapter) -> Chapter:
        """更新章节"""
        async with self.async_session() as session:
            stmt = (
                update(ChapterModel)
                .where(
                    ChapterModel.tenant_id == uuid.UUID(tenant_id),
                    ChapterModel.id == chapter.id,
                )
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
