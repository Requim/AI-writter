"""小说仓储实现"""

import json
import uuid
from dataclasses import replace
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import Any, Optional, List

from service.entities.novel import Novel
from service.entities.chapter import Chapter
from service.ports.novel_repository import NovelRepository
from service.ports.novel_plan_repository import (
    NovelPlanRepository,
    PlanVersionConflictError,
)
from service.ports.tactical_plan_repository import (
    TacticalPlanRepository,
    TacticalPlanVersionConflictError,
)
from service.value_objects.novel_plan import (
    NovelPlan,
    NovelPlanVersionSummary,
    PlanExecution,
)
from service.value_objects.tactical_plan import TacticalWindow
from service.value_objects.outline import Outline
from service.value_objects.progress import Progress
from .models import (
    Base,
    ChapterModel,
    MemoryModel,
    NovelModel,
    NovelPlanExecutionModel,
    NovelPlanVersionModel,
    NovelTacticalPlanVersionModel,
)


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
    await _delete_plan_executions(
        session,
        tenant_id,
        novel_id,
        chapter_index + 1,
        from_chapter=discard_following,
    )


async def _delete_plan_executions(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    chapter_number: int,
    *,
    from_chapter: bool,
) -> None:
    predicate = (
        NovelPlanExecutionModel.chapter_number >= chapter_number
        if from_chapter
        else NovelPlanExecutionModel.chapter_number == chapter_number
    )
    await session.execute(
        delete(NovelPlanExecutionModel).where(
            NovelPlanExecutionModel.tenant_id == tenant_id,
            NovelPlanExecutionModel.novel_id == novel_id,
            predicate,
        )
    )


async def _set_novel_progress(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    progress: Progress,
    updated_at: datetime,
) -> None:
    payload = await _merge_plan_progress(
        session, tenant_id, novel_id, progress.to_dict()
    )
    await session.execute(
        update(NovelModel)
        .where(NovelModel.tenant_id == tenant_id, NovelModel.id == novel_id)
        .values(
            progress=payload,
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
    await _delete_plan_executions(
        session,
        tenant_id,
        novel_id,
        rewind_to + 1,
        from_chapter=True,
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


async def _latest_plan_model(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID
) -> NovelPlanVersionModel | None:
    result = await session.execute(
        select(NovelPlanVersionModel)
        .where(
            NovelPlanVersionModel.tenant_id == tenant_id,
            NovelPlanVersionModel.novel_id == novel_id,
        )
        .order_by(NovelPlanVersionModel.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _plan_model_for_idempotency_key(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID,
    idempotency_key: str,
) -> NovelPlanVersionModel | None:
    result = await session.execute(
        select(NovelPlanVersionModel).where(
            NovelPlanVersionModel.tenant_id == tenant_id,
            NovelPlanVersionModel.novel_id == novel_id,
            NovelPlanVersionModel.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


def _plan_from_model(model: NovelPlanVersionModel) -> NovelPlan:
    payload = dict(model.plan_data or {})
    payload.update(
        version=model.version,
        source=model.source,
        created_at=model.created_at,
    )
    return NovelPlan.from_dict(payload)


def _plan_content(plan: NovelPlan) -> dict[str, Any]:
    payload = plan.to_dict()
    payload.pop("version", None)
    payload.pop("created_at", None)
    return payload


def _idempotent_plan_result(
    model: NovelPlanVersionModel, plan: NovelPlan
) -> NovelPlan:
    accepted = _plan_from_model(model)
    if _plan_content(accepted) != _plan_content(plan):
        raise PlanVersionConflictError("整书计划幂等键已被不同内容占用")
    return accepted


def _plan_version_model(
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    plan: NovelPlan,
    idempotency_key: str,
    created_by_user_id: str | None,
    trigger_chapter: int | None,
    change_summary: str,
) -> NovelPlanVersionModel:
    return NovelPlanVersionModel(
        tenant_id=tenant_id,
        novel_id=novel_id,
        version=plan.version,
        source=plan.source,
        trigger_chapter=trigger_chapter,
        change_summary=change_summary,
        idempotency_key=idempotency_key,
        plan_data=plan.to_dict(),
        created_by_user_id=(
            uuid.UUID(created_by_user_id) if created_by_user_id else None
        ),
        created_at=plan.created_at,
    )


def _execution_from_model(model: NovelPlanExecutionModel) -> PlanExecution:
    return PlanExecution.from_dict(
        {
            "chapter_number": model.chapter_number,
            "plan_version": model.plan_version,
            "status": model.status,
            "actual_words": model.actual_words,
            "fulfillment": model.fulfillment or {},
            "drift_severity": model.drift_severity,
            "updated_at": model.updated_at,
            "tactical_version": model.tactical_version,
        }
    )


async def _latest_tactical_model(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID
) -> NovelTacticalPlanVersionModel | None:
    result = await session.execute(
        select(NovelTacticalPlanVersionModel)
        .where(
            NovelTacticalPlanVersionModel.tenant_id == tenant_id,
            NovelTacticalPlanVersionModel.novel_id == novel_id,
        )
        .order_by(NovelTacticalPlanVersionModel.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _tactical_model_for_idempotency_key(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID,
    idempotency_key: str,
) -> NovelTacticalPlanVersionModel | None:
    result = await session.execute(
        select(NovelTacticalPlanVersionModel).where(
            NovelTacticalPlanVersionModel.tenant_id == tenant_id,
            NovelTacticalPlanVersionModel.novel_id == novel_id,
            NovelTacticalPlanVersionModel.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def _tactical_model_by_version(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID, version: int
) -> NovelTacticalPlanVersionModel | None:
    result = await session.execute(
        select(NovelTacticalPlanVersionModel).where(
            NovelTacticalPlanVersionModel.tenant_id == tenant_id,
            NovelTacticalPlanVersionModel.novel_id == novel_id,
            NovelTacticalPlanVersionModel.version == version,
        )
    )
    return result.scalar_one_or_none()


def _tactical_from_model(model: NovelTacticalPlanVersionModel) -> TacticalWindow:
    payload = dict(model.window_data or {})
    payload.update(
        version=model.version,
        novel_plan_version=model.novel_plan_version,
        story_state_revision=model.story_state_revision,
        start_chapter=model.window_start,
        end_chapter=model.window_end,
        source=model.source,
        created_at=model.created_at,
    )
    return TacticalWindow.from_dict(payload)


def _tactical_content(window: TacticalWindow) -> dict[str, object]:
    payload = window.to_dict()
    payload.pop("version", None)
    payload.pop("created_at", None)
    return payload


def _same_tactical_request(
    model: NovelTacticalPlanVersionModel, window: TacticalWindow
) -> bool:
    return _tactical_content(_tactical_from_model(model)) == _tactical_content(window)


def _idempotent_tactical_result(
    model: NovelTacticalPlanVersionModel, window: TacticalWindow
) -> TacticalWindow:
    if not _same_tactical_request(model, window):
        raise TacticalPlanVersionConflictError("战术幂等键已被不同内容占用")
    return _tactical_from_model(model)


def _tactical_model(
    tenant_id: uuid.UUID, novel_id: uuid.UUID, window: TacticalWindow,
    idempotency_key: str, created_by_user_id: str | None,
) -> NovelTacticalPlanVersionModel:
    return NovelTacticalPlanVersionModel(
        tenant_id=tenant_id,
        novel_id=novel_id,
        version=window.version,
        novel_plan_version=window.novel_plan_version,
        story_state_revision=window.story_state_revision,
        window_start=window.start_chapter,
        window_end=window.end_chapter,
        source=window.source,
        idempotency_key=idempotency_key,
        window_data=window.to_dict(),
        created_by_user_id=(
            uuid.UUID(created_by_user_id) if created_by_user_id else None
        ),
        created_at=window.created_at,
    )


async def _assert_tactical_plan_link(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID,
    window: TacticalWindow,
) -> None:
    plan = await _latest_plan_model(session, tenant_id, novel_id)
    if plan is None or plan.version != window.novel_plan_version:
        raise TacticalPlanVersionConflictError("整书计划已更新，战术窗口已过期")


async def _assert_execution_versions(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID,
    execution: PlanExecution,
) -> None:
    current = await _latest_plan_model(session, tenant_id, novel_id)
    if current is None or current.version != execution.plan_version:
        raise PlanVersionConflictError("计划已更新，执行记录已过期")
    if execution.tactical_version is None:
        return
    tactical = await _tactical_model_by_version(
        session, tenant_id, novel_id, execution.tactical_version
    )
    if tactical is None or tactical.novel_plan_version != execution.plan_version:
        raise TacticalPlanVersionConflictError("战术计划已更新，执行记录已过期")
    if not tactical.window_start <= execution.chapter_number <= tactical.window_end:
        raise TacticalPlanVersionConflictError(
            f"战术窗口未覆盖第 {execution.chapter_number} 章执行记录"
        )


def _normalize_tactical_idempotency_key(value: str) -> str:
    key = (value or "").strip()
    if not key:
        raise ValueError("战术计划幂等键不能为空")
    if len(key) > 128:
        raise ValueError("战术计划幂等键不得超过 128 个字符")
    return key


def _normalize_plan_idempotency_key(value: str) -> str:
    key = (value or "").strip()
    if not key:
        raise ValueError("整书计划幂等键不能为空")
    if len(key) > 128:
        raise ValueError("整书计划幂等键不得超过 128 个字符")
    return key


async def _sync_plan_mirrors(
    session: AsyncSession, novel: NovelModel, plan: NovelPlan
) -> None:
    outline = dict(novel.total_outline or {})
    outline.pop("chapters", None)
    outline["total_chapters"] = plan.scale.target_chapters
    outline["volumes"] = plan.to_dict()["volumes"]
    outline["scale"] = plan.scale.to_dict()
    novel.total_outline = outline
    progress = dict(novel.progress or {})
    completed_words = await _completed_word_count(
        session, novel.tenant_id, novel.id
    )
    progress.update(_plan_progress_fields(plan, progress, completed_words))
    novel.progress = progress


async def _completed_word_count(
    session: AsyncSession, tenant_id: uuid.UUID, novel_id: uuid.UUID
) -> int:
    result = await session.execute(
        select(func.coalesce(func.sum(ChapterModel.word_count), 0)).where(
            ChapterModel.tenant_id == tenant_id,
            ChapterModel.novel_id == novel_id,
        )
    )
    return int(result.scalar_one())


def _volume_progress_fields(plan: NovelPlan, current: int) -> dict[str, int | float]:
    if not plan.volumes:
        return {"current_volume": 0, "total_volumes": 0, "volume_percentage": 0.0}
    chapter = min(max(current + 1, 1), plan.scale.target_chapters)
    volume = next(
        item
        for item in plan.volumes
        if item.start_chapter <= chapter <= item.end_chapter
    )
    length = volume.end_chapter - volume.start_chapter + 1
    completed = max(0, min(current, volume.end_chapter) - volume.start_chapter + 1)
    return {
        "current_volume": plan.volumes.index(volume) + 1,
        "total_volumes": len(plan.volumes),
        "volume_percentage": completed / length * 100 if length else 0.0,
    }


def _plan_progress_fields(
    plan: NovelPlan,
    progress: dict,
    completed_words: int,
    *,
    plan_status: str = "accepted",
    drift_severity: str = "none",
) -> dict[str, object]:
    target_words = plan.scale.target_total_words
    fields: dict[str, object] = {
        "total_chapters": plan.scale.target_chapters,
        "target_words": target_words,
        "completed_words": completed_words,
        "word_percentage": completed_words / target_words * 100,
        "plan_version": plan.version,
        "plan_status": plan_status,
        "drift_severity": drift_severity,
    }
    fields.update(_volume_progress_fields(plan, int(progress.get("current_chapter", 0))))
    return fields


async def _merge_plan_progress(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    novel_id: uuid.UUID,
    progress: dict,
) -> dict:
    model = await _latest_plan_model(session, tenant_id, novel_id)
    if model is None:
        return progress
    stored = (
        await session.execute(
            select(NovelModel.progress).where(
                NovelModel.tenant_id == tenant_id,
                NovelModel.id == novel_id,
            )
        )
    ).scalar_one_or_none() or {}
    completed_words = await _completed_word_count(session, tenant_id, novel_id)
    progress.update(
        _plan_progress_fields(
            _plan_from_model(model),
            progress,
            completed_words,
            plan_status=str(stored.get("plan_status") or "accepted"),
            drift_severity=str(stored.get("drift_severity") or "none"),
        )
    )
    return progress


async def _mark_rewind_progress(
    session: AsyncSession, novel: NovelModel
) -> None:
    progress = dict(novel.progress or {})
    completed_words = await _completed_word_count(session, novel.tenant_id, novel.id)
    model = await _latest_plan_model(session, novel.tenant_id, novel.id)
    if model is None:
        target = int(progress.get("target_words", 0) or 0)
        progress.update(
            completed_words=completed_words,
            word_percentage=completed_words / target * 100 if target else 0.0,
        )
    else:
        progress.update(
            _plan_progress_fields(
                _plan_from_model(model), progress, completed_words,
                plan_status="needs_reconciliation", drift_severity="minor",
            )
        )
    novel.progress = progress


def _record_execution_progress(
    novel: NovelModel, execution: PlanExecution
) -> None:
    statuses = {
        "none": "accepted",
        "minor": "needs_reconciliation",
        "major": "needs_review",
    }
    progress = dict(novel.progress or {})
    progress.update(
        plan_version=execution.plan_version,
        plan_status=statuses[execution.drift_severity],
        drift_severity=execution.drift_severity,
    )
    novel.progress = progress


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
    if int(progress_data.get("plan_version", 0) or 0) > 0:
        progress_data["plan_status"] = "needs_reconciliation"
        progress_data["drift_severity"] = "minor"
    novel.progress = progress_data
    novel.updated_at = updated_at


class PostgresNovelRepository(
    NovelRepository, NovelPlanRepository, TacticalPlanRepository
):
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
        tenant_uuid = uuid.UUID(tenant_id)
        chapter_uuid = uuid.UUID(chapter_id)
        async with self.async_session() as session, session.begin():
            location = (
                await session.execute(
                    select(ChapterModel.novel_id, ChapterModel.chapter_index).where(
                        ChapterModel.tenant_id == tenant_uuid,
                        ChapterModel.id == chapter_uuid,
                    )
                )
            ).one_or_none()
            if location is None:
                return
            await session.execute(delete(ChapterModel).where(
                ChapterModel.tenant_id == uuid.UUID(tenant_id),
                ChapterModel.id == chapter_uuid,
            ))
            await _delete_plan_executions(
                session, tenant_uuid, location.novel_id,
                location.chapter_index + 1, from_chapter=False,
            )

    async def delete_chapters_by_index(
        self, tenant_id: str, novel_id: str, chapter_index: int
    ) -> None:
        """删除指定小说和章节索引的所有旧版本章节（upsert 用）"""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            await session.execute(
                delete(ChapterModel)
                .where(ChapterModel.tenant_id == tenant_uuid)
                .where(ChapterModel.novel_id == novel_uuid)
                .where(ChapterModel.chapter_index == chapter_index)
            )
            await _delete_plan_executions(
                session, tenant_uuid, novel_uuid,
                chapter_index + 1, from_chapter=False,
            )

    async def mark_continuity_reconciliation_needed(
        self, tenant_id: str, novel_id: str
    ) -> None:
        """Keep rewritten chapters while invalidating continuity-derived tactics."""
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                raise RuntimeError("连续性标记失败：目标小说不存在")
            progress = dict(novel.progress or {})
            if (
                int(progress.get("plan_version", 0) or 0) > 0
                and progress.get("plan_status") != "needs_review"
            ):
                progress["plan_status"] = "needs_reconciliation"
            novel.progress = progress
            novel.updated_at = datetime.now()

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
            await _mark_rewind_progress(session, novel)
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
            await _delete_plan_executions(
                session,
                tenant_uuid,
                novel_uuid,
                chapter.chapter_index + 1,
                from_chapter=False,
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

    async def get_latest_plan(
        self, tenant_id: str, novel_id: str
    ) -> NovelPlan | None:
        async with self.async_session() as session:
            model = await _latest_plan_model(
                session, uuid.UUID(tenant_id), uuid.UUID(novel_id)
            )
            return _plan_from_model(model) if model else None

    async def list_plan_versions(
        self, tenant_id: str, novel_id: str
    ) -> list[NovelPlan]:
        async with self.async_session() as session:
            result = await session.execute(
                select(NovelPlanVersionModel)
                .where(
                    NovelPlanVersionModel.tenant_id == uuid.UUID(tenant_id),
                    NovelPlanVersionModel.novel_id == uuid.UUID(novel_id),
                )
                .order_by(NovelPlanVersionModel.version.desc())
            )
            return [_plan_from_model(model) for model in result.scalars()]

    async def list_plan_version_summaries(
        self, tenant_id: str, novel_id: str
    ) -> list[NovelPlanVersionSummary]:
        async with self.async_session() as session:
            result = await session.execute(
                select(NovelPlanVersionModel)
                .where(
                    NovelPlanVersionModel.tenant_id == uuid.UUID(tenant_id),
                    NovelPlanVersionModel.novel_id == uuid.UUID(novel_id),
                )
                .order_by(NovelPlanVersionModel.version.desc())
            )
            return [
                NovelPlanVersionSummary(
                    version=model.version,
                    source=model.source,
                    trigger_chapter=model.trigger_chapter,
                    change_summary=model.change_summary,
                    created_by_user_id=(
                        str(model.created_by_user_id)
                        if model.created_by_user_id
                        else None
                    ),
                    created_at=model.created_at,
                )
                for model in result.scalars()
            ]

    async def accept_plan(
        self,
        tenant_id: str,
        novel_id: str,
        plan: NovelPlan,
        expected_version: int,
        *,
        idempotency_key: str,
        created_by_user_id: str | None = None,
        trigger_chapter: int | None = None,
        change_summary: str = "",
    ) -> NovelPlan:
        plan.assert_valid()
        if expected_version < 0:
            raise ValueError("预期整书计划版本不得为负数")
        if trigger_chapter is not None and trigger_chapter < 1:
            raise ValueError("触发章节必须大于等于 1")
        normalized_key = _normalize_plan_idempotency_key(idempotency_key)
        tenant_uuid = uuid.UUID(tenant_id)
        novel_uuid = uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                raise RuntimeError("计划保存失败：目标小说不存在")
            existing = await _plan_model_for_idempotency_key(
                session, tenant_uuid, novel_uuid, normalized_key
            )
            if existing is not None:
                return _idempotent_plan_result(existing, plan)
            current = await _latest_plan_model(session, tenant_uuid, novel_uuid)
            current_version = current.version if current else 0
            if current_version != expected_version:
                raise PlanVersionConflictError("计划已更新，请刷新后重试")
            accepted_plan = replace(plan, version=current_version + 1)
            session.add(_plan_version_model(
                tenant_uuid, novel_uuid, accepted_plan, normalized_key,
                created_by_user_id, trigger_chapter, change_summary,
            ))
            await _sync_plan_mirrors(session, novel, accepted_plan)
        return accepted_plan

    async def list_plan_executions(
        self, tenant_id: str, novel_id: str
    ) -> list[PlanExecution]:
        async with self.async_session() as session:
            result = await session.execute(
                select(NovelPlanExecutionModel)
                .where(
                    NovelPlanExecutionModel.tenant_id == uuid.UUID(tenant_id),
                    NovelPlanExecutionModel.novel_id == uuid.UUID(novel_id),
                )
                .order_by(NovelPlanExecutionModel.chapter_number)
            )
            return [_execution_from_model(model) for model in result.scalars()]

    async def upsert_plan_execution(
        self, tenant_id: str, novel_id: str, execution: PlanExecution
    ) -> PlanExecution:
        tenant_uuid, novel_uuid = uuid.UUID(tenant_id), uuid.UUID(novel_id)
        values: dict[str, Any] = {
            "tenant_id": tenant_uuid,
            "novel_id": novel_uuid,
            "chapter_number": execution.chapter_number,
            "plan_version": execution.plan_version,
            "tactical_version": execution.tactical_version,
            "status": execution.status,
            "actual_words": execution.actual_words,
            "fulfillment": execution.fulfillment,
            "drift_severity": execution.drift_severity,
            "updated_at": execution.updated_at,
        }
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(
                session, tenant_uuid, novel_uuid
            )
            if novel is None:
                raise RuntimeError("计划执行记录保存失败：目标小说不存在")
            await _assert_execution_versions(
                session, tenant_uuid, novel_uuid, execution
            )
            statement = pg_insert(NovelPlanExecutionModel).values(**values)
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_plan_executions_chapter",
                    set_={key: values[key] for key in (
                        "plan_version", "tactical_version", "status",
                        "actual_words", "fulfillment", "drift_severity", "updated_at",
                    )},
                )
            )
            _record_execution_progress(novel, execution)
        return execution

    async def delete_plan_executions_from(
        self, tenant_id: str, novel_id: str, chapter_number: int
    ) -> None:
        async with self.async_session() as session, session.begin():
            await session.execute(
                delete(NovelPlanExecutionModel).where(
                    NovelPlanExecutionModel.tenant_id == uuid.UUID(tenant_id),
                    NovelPlanExecutionModel.novel_id == uuid.UUID(novel_id),
                    NovelPlanExecutionModel.chapter_number >= chapter_number,
                )
            )

    async def get_latest_tactical_plan(
        self, tenant_id: str, novel_id: str
    ) -> TacticalWindow | None:
        async with self.async_session() as session:
            model = await _latest_tactical_model(
                session, uuid.UUID(tenant_id), uuid.UUID(novel_id)
            )
            return _tactical_from_model(model) if model else None

    async def list_tactical_plan_versions(
        self, tenant_id: str, novel_id: str
    ) -> list[TacticalWindow]:
        async with self.async_session() as session:
            result = await session.execute(
                select(NovelTacticalPlanVersionModel)
                .where(
                    NovelTacticalPlanVersionModel.tenant_id == uuid.UUID(tenant_id),
                    NovelTacticalPlanVersionModel.novel_id == uuid.UUID(novel_id),
                )
                .order_by(NovelTacticalPlanVersionModel.version.desc())
            )
            return [_tactical_from_model(model) for model in result.scalars()]

    async def accept_tactical_plan(
        self, tenant_id: str, novel_id: str, window: TacticalWindow,
        expected_version: int, *, idempotency_key: str,
        created_by_user_id: str | None = None,
    ) -> TacticalWindow:
        window.assert_valid()
        if expected_version < 0:
            raise ValueError("预期战术版本不得为负数")
        normalized_key = _normalize_tactical_idempotency_key(idempotency_key)
        tenant_uuid, novel_uuid = uuid.UUID(tenant_id), uuid.UUID(novel_id)
        async with self.async_session() as session, session.begin():
            novel = await _lock_novel(session, tenant_uuid, novel_uuid)
            if novel is None:
                raise RuntimeError("战术计划保存失败：目标小说不存在")
            await _assert_tactical_plan_link(
                session, tenant_uuid, novel_uuid, window
            )
            existing = await _tactical_model_for_idempotency_key(
                session, tenant_uuid, novel_uuid, normalized_key
            )
            if existing is not None:
                return _idempotent_tactical_result(existing, window)
            current = await _latest_tactical_model(session, tenant_uuid, novel_uuid)
            current_version = current.version if current else 0
            if current_version != expected_version:
                raise TacticalPlanVersionConflictError("战术计划已更新，请刷新后重试")
            accepted = replace(window, version=current_version + 1)
            session.add(_tactical_model(
                tenant_uuid, novel_uuid, accepted,
                normalized_key, created_by_user_id,
            ))
        return accepted
