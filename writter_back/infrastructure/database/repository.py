"""小说仓储实现"""

import json
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import delete, select, text, update
from typing import Optional, List

from service.entities.novel import Novel
from service.entities.chapter import Chapter
from service.ports.novel_repository import NovelRepository
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from .models import Base, ChapterModel, MemoryModel, NovelModel


async def _lock_novel(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID
) -> NovelModel | None:
    return (
        await session.execute(
            select(NovelModel)
            .where(NovelModel.tenant_id == tenant_id, NovelModel.id == novel_id)
            .with_for_update()
        )
    ).scalar_one_or_none()


def _checkpoint_sync_request(
    next_index: int, discard_from_index: int, is_completed: bool
) -> dict[str, object]:
    return {
        "next_index": next_index,
        "discard_from_index": discard_from_index,
        "is_completed": is_completed,
    }


async def _delete_chapter_memories(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter_index: int,
    *,
    from_index: bool,
) -> None:
    comparison = ">=" if from_index else "="
    await session.execute(
        text(
            "DELETE FROM novel_memories "
            "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
            "AND metadata->>'type' IN ('chapter', 'chapter_summary') "
            "AND (metadata->>'chapter_index')::integer "
            f"{comparison} :chapter_index"
        ),
        {
            "tenant_id": tenant_id,
            "novel_id": novel_id,
            "chapter_index": chapter_index,
        },
    )


async def _delete_memory_types(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    memory_types: list[str],
) -> None:
    for memory_type in memory_types:
        await session.execute(
            text(
                "DELETE FROM novel_memories "
                "WHERE tenant_id = :tenant_id AND novel_id = :novel_id "
                "AND metadata @> CAST(:metadata AS jsonb)"
            ),
            {
                "tenant_id": tenant_id,
                "novel_id": novel_id,
                "metadata": json.dumps({"type": memory_type}),
            },
        )


async def _replace_edited_memories(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter: Chapter,
    memory_content: str,
    memory_metadata: dict,
    chapter_summary: str,
) -> None:
    await _delete_chapter_memories(
        session,
        tenant_id,
        novel_id,
        chapter.chapter_index,
        from_index=False,
    )
    await _delete_memory_types(
        session, tenant_id, novel_id, ["story_state", "rolling_plan"]
    )
    session.add_all(
        [
            MemoryModel(
                tenant_id=tenant_id,
                novel_id=novel_id,
                content=memory_content,
                meta_data=memory_metadata,
            ),
            MemoryModel(
                tenant_id=tenant_id,
                novel_id=novel_id,
                content=chapter_summary,
                meta_data={
                    "type": "chapter_summary",
                    "chapter_index": chapter.chapter_index,
                },
            ),
        ]
    )


def _chapter_model(
    tenant_id: uuid.UUID, novel_id: uuid.UUID, chapter: Chapter
) -> ChapterModel:
    return ChapterModel(
        id=chapter.id,
        tenant_id=tenant_id,
        novel_id=novel_id,
        chapter_index=chapter.chapter_index,
        title=chapter.title,
        outline=chapter.outline,
        content=chapter.content,
        word_count=chapter.word_count,
        reflection_issues=chapter.reflection_issues or None,
        user_decision=chapter.user_decision,
        revision_count=chapter.revision_count,
        revision_history=chapter.revision_history or None,
        version=chapter.version,
        status=chapter.status,
        created_at=chapter.created_at,
        updated_at=chapter.updated_at,
    )


def _add_continuity_memories(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter: Chapter,
    memory_content: str,
    memory_metadata: dict,
    chapter_summary: str | None,
    story_state: str | None,
    rolling_plan: str | None,
) -> None:
    session.add(
        MemoryModel(
            tenant_id=tenant_id,
            novel_id=novel_id,
            content=memory_content,
            meta_data=memory_metadata,
        )
    )
    derived = (
        ("chapter_summary", chapter_summary),
        ("story_state", story_state),
        ("rolling_plan", rolling_plan),
    )
    for memory_type, content in derived:
        if content is None:
            continue
        session.add(
            MemoryModel(
                tenant_id=tenant_id,
                novel_id=novel_id,
                content=content,
                meta_data={
                    "type": memory_type,
                    "chapter_index": chapter.chapter_index,
                },
            )
        )


async def _delete_replaced_data(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter_index: int,
    *,
    discard_following: bool,
    invalidated_types: list[str],
) -> None:
    predicate = (
        ChapterModel.chapter_index >= chapter_index
        if discard_following
        else ChapterModel.chapter_index == chapter_index
    )
    await session.execute(
        delete(ChapterModel).where(
            ChapterModel.tenant_id == tenant_id,
            ChapterModel.novel_id == novel_id,
            predicate,
        )
    )
    await _delete_chapter_memories(
        session,
        tenant_id,
        novel_id,
        chapter_index,
        from_index=discard_following,
    )
    await _delete_memory_types(session, tenant_id, novel_id, invalidated_types)


async def _set_novel_progress(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    progress: Progress,
    updated_at: datetime,
) -> None:
    await session.execute(
        update(NovelModel)
        .where(NovelModel.tenant_id == tenant_id, NovelModel.id == novel_id)
        .values(
            progress=progress.to_dict(),
            status=progress.status,
            updated_at=updated_at,
        )
    )


async def _selected_rewind_index(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter_ids: list[uuid.UUID],
) -> int | None:
    rows = (
        await session.execute(
            select(ChapterModel.chapter_index).where(
                ChapterModel.tenant_id == tenant_id,
                ChapterModel.novel_id == novel_id,
                ChapterModel.id.in_(chapter_ids),
            )
        )
    ).all()
    return min((row.chapter_index for row in rows), default=None)


async def _delete_chapters_from(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    rewind_to: int,
) -> int:
    rows = (
        await session.execute(
            select(ChapterModel.id).where(
                ChapterModel.tenant_id == tenant_id,
                ChapterModel.novel_id == novel_id,
                ChapterModel.chapter_index >= rewind_to,
            )
        )
    ).all()
    await session.execute(
        delete(ChapterModel).where(
            ChapterModel.tenant_id == tenant_id,
            ChapterModel.novel_id == novel_id,
            ChapterModel.chapter_index >= rewind_to,
        )
    )
    await _delete_chapter_memories(
        session, tenant_id, novel_id, rewind_to, from_index=True
    )
    await _delete_memory_types(
        session, tenant_id, novel_id, ["story_state", "rolling_plan"]
    )
    return len(rows)


def _rewind_novel_progress(novel: NovelModel, rewind_to: int) -> None:
    progress_data = dict(novel.progress or {})
    total = int(progress_data.get("total_chapters", 0) or 0)
    progress_data.update(
        {
            "current_chapter": rewind_to,
            "percentage": (rewind_to / total * 100) if total else 0,
            "status": "writing" if rewind_to else "draft",
            "checkpoint_sync": _checkpoint_sync_request(rewind_to, rewind_to, False),
        }
    )
    novel.progress = progress_data
    novel.status = progress_data["status"]


async def _update_chapter_row(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter: Chapter,
    expected_version: int,
) -> bool:
    result = await session.execute(
        update(ChapterModel)
        .where(
            ChapterModel.tenant_id == tenant_id,
            ChapterModel.novel_id == novel_id,
            ChapterModel.id == chapter.id,
            ChapterModel.version == expected_version,
        )
        .values(
            title=chapter.title,
            content=chapter.content,
            word_count=chapter.word_count,
            version=expected_version + 1,
            updated_at=chapter.updated_at,
        )
    )
    return result.rowcount == 1


def _mark_edit_checkpoint_sync(novel: NovelModel, updated_at: datetime) -> None:
    progress_data = dict(novel.progress or {})
    current_index = int(progress_data.get("current_chapter", 0) or 0)
    is_completed = progress_data.get("status") == "completed"
    progress_data["checkpoint_sync"] = _checkpoint_sync_request(
        current_index,
        current_index,
        is_completed,
    )
    novel.progress = progress_data
    novel.updated_at = updated_at


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
                total_outline=novel.total_outline.__dict__
                if novel.total_outline
                else None,
                progress=novel.progress.to_dict() if novel.progress else None,
                status=novel.progress.status if novel.progress else "draft",
                thread_id=novel.thread_id,
                created_at=novel.created_at,
                updated_at=novel.updated_at,
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

            outline = (
                Outline(**novel_model.total_outline)
                if novel_model.total_outline
                else None
            )
            progress = (
                Progress(**novel_model.progress) if novel_model.progress else Progress()
            )

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
                updated_at=novel_model.updated_at,
            )

    async def find_by_id_with_chapters(
        self, tenant_id: str, novel_id: str
    ) -> Optional[Novel]:
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

            outline = (
                Outline(**novel_model.total_outline)
                if novel_model.total_outline
                else None
            )
            progress = (
                Progress(**novel_model.progress) if novel_model.progress else Progress()
            )

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
                updated_at=novel_model.updated_at,
            )

            # 加载章节
            chapters_stmt = (
                select(ChapterModel)
                .where(
                    ChapterModel.tenant_id == tenant_uuid,
                    ChapterModel.novel_id == uuid.UUID(novel_id),
                )
                .order_by(ChapterModel.chapter_index)
            )
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
                    version=cm.version,
                    status=cm.status,
                    created_at=cm.created_at,
                    updated_at=cm.updated_at,
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
                    total_outline=Outline(**n.total_outline)
                    if n.total_outline
                    else None,
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
                    total_outline=novel.total_outline.__dict__
                    if novel.total_outline
                    else None,
                    progress=novel.progress.to_dict() if novel.progress else None,
                    status=novel.progress.status if novel.progress else "draft",
                    updated_at=novel.updated_at,
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
                version=chapter.version,
                status=chapter.status,
                created_at=chapter.created_at,
                updated_at=chapter.updated_at,
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
        *,
        chapter_summary: str | None = None,
        story_state: str | None = None,
        rolling_plan: str | None = None,
        discard_following: bool = False,
    ) -> Chapter:
        """Atomically replace a chapter and every continuity artifact derived from it."""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            if await _lock_novel(session, tenant_uuid, novel_uuid) is None:
                raise RuntimeError("章节保存失败：目标小说不存在")
            if discard_following:
                progress.checkpoint_sync = _checkpoint_sync_request(
                    chapter.chapter_index + 1,
                    chapter.chapter_index,
                    progress.is_complete(),
                )
            invalidated_types = [
                memory_type
                for memory_type, should_invalidate in (
                    ("story_state", story_state is not None or discard_following),
                    ("rolling_plan", rolling_plan is not None or discard_following),
                )
                if should_invalidate
            ]
            await _delete_replaced_data(
                session,
                tenant_uuid,
                novel_uuid,
                chapter.chapter_index,
                discard_following=discard_following,
                invalidated_types=invalidated_types,
            )
            session.add(_chapter_model(tenant_uuid, novel_uuid, chapter))
            _add_continuity_memories(
                session,
                tenant_uuid,
                novel_uuid,
                chapter,
                memory_content,
                memory_metadata,
                chapter_summary,
                story_state,
                rolling_plan,
            )
            await _set_novel_progress(
                session, tenant_uuid, novel_uuid, progress, chapter.updated_at
            )
        return chapter

    async def rewind_chapters_atomically(
        self, tenant_id: str, novel_id: str, chapter_ids: list[str]
    ) -> tuple[int, int | None]:
        """从所选最早章节起删除正文和派生连续性数据，并回退进度。"""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        ids = [uuid.UUID(chapter_id) for chapter_id in chapter_ids]
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                return 0, None
            rewind_to = await _selected_rewind_index(
                session, tenant_uuid, novel_uuid, ids
            )
            if rewind_to is None:
                return 0, None
            deleted = await _delete_chapters_from(
                session, tenant_uuid, novel_uuid, rewind_to
            )
            _rewind_novel_progress(novel, rewind_to)
        return deleted, rewind_to

    async def delete_chapters_atomically(
        self, tenant_id: str, novel_id: str, chapter_ids: list[str]
    ) -> tuple[int, int | None]:
        """兼容旧调用，批量删除统一执行章节回退语义。"""
        return await self.rewind_chapters_atomically(tenant_id, novel_id, chapter_ids)

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
                version=cm.version,
                status=cm.status,
                created_at=cm.created_at,
                updated_at=cm.updated_at,
            )

    async def update_chapter_consistently(
        self,
        tenant_id: str,
        novel_id: str,
        chapter: Chapter,
        expected_version: int,
        memory_content: str,
        memory_metadata: dict,
        chapter_summary: str,
    ) -> Chapter | None:
        """用乐观锁原子更新章节、章节记忆，并失效累计连续性缓存。"""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        next_version = expected_version + 1
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                return None
            updated = await _update_chapter_row(
                session,
                tenant_uuid,
                novel_uuid,
                chapter,
                expected_version,
            )
            if not updated:
                return None
            await _replace_edited_memories(
                session,
                tenant_uuid,
                novel_uuid,
                chapter,
                memory_content,
                memory_metadata,
                chapter_summary,
            )
            _mark_edit_checkpoint_sync(novel, chapter.updated_at)
        chapter.version = next_version
        return chapter

    async def clear_checkpoint_sync(
        self,
        tenant_id: str,
        novel_id: str,
        expected_request: dict[str, object],
    ) -> bool:
        """仅在请求仍匹配时清除 checkpoint 补偿标记。"""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                return False
            progress_data = dict(novel.progress or {})
            if progress_data.get("checkpoint_sync") != expected_request:
                return False
            progress_data.pop("checkpoint_sync", None)
            novel.progress = progress_data
        return True
