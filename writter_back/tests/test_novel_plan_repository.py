"""PostgreSQL 规划仓储的版本、租户与回退语义。"""

from uuid import UUID

import pytest

from service.entities.chapter import Chapter
from service.ports.novel_plan_repository import PlanVersionConflictError
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    PlanExecution,
    ScaleContract,
    StoryArc,
    VolumePlan,
)
from service.value_objects.progress import Progress


def _plan(chapters: int = 3, source: str = "initial") -> NovelPlan:
    target_words = chapters * 4200
    slots = [
        ChapterSlot(
            chapter_number=number,
            volume_id="vol-1",
            arc_ids=["main"],
            story_function=f"推进第 {number} 章",
            must_happen=["关键事件"],
            planned_state_delta="局势变化",
            target_words=4200,
        )
        for number in range(1, chapters + 1)
    ]
    return NovelPlan(
        scale=ScaleContract("custom", chapters, target_words),
        ending_contract={"final_state": "主线闭合"},
        volumes=[VolumePlan(
            "vol-1", "第一卷", 1, chapters, target_words,
            opening_state="危机出现", midpoint_turn="认知逆转",
            climax="正面对抗", ending_state="阶段结束",
        )],
        arcs=[StoryArc(
            "main", "main", 1, chapters, "完成主线",
            [{"chapter_number": max(1, chapters // 2), "change": "冲突升级"}],
            "主线闭合", True,
        )],
        chapter_slots=slots,
        source=source,
    )


async def _store_chapter(repository, tenant_id: str, novel_id: str, index: int) -> Chapter:
    chapter = Chapter(
        novel_id=UUID(novel_id),
        chapter_index=index,
        title=f"第 {index + 1} 章",
        outline={"chapter_number": index + 1},
        content="正文",
        word_count=4200,
        status="completed",
    )
    progress = Progress(
        current_chapter=index + 1,
        total_chapters=3,
        percentage=(index + 1) / 3 * 100,
        status="completed" if index == 2 else "writing",
    )
    await repository.replace_chapter(
        tenant_id,
        novel_id,
        chapter,
        chapter.content,
        {"type": "chapter", "chapter_index": index},
        progress,
        chapter_summary="摘要",
    )
    return chapter


@pytest.mark.asyncio
async def test_accept_plan_updates_immutable_version_and_mirrors(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id = str(tenant_context.tenant_id)
    await repository.save(tenant_id, sample_novel)
    candidate = _plan()

    accepted = await repository.accept_plan(
        tenant_id, str(sample_novel.id), candidate, 0,
        created_by_user_id=str(tenant_context.user_id),
    )
    saved = await repository.find_by_id(tenant_id, str(sample_novel.id))

    assert candidate.version == 0 and accepted.version == 1
    assert saved is not None and saved.total_outline is not None
    assert saved.total_outline.total_chapters == 3
    assert saved.total_outline.chapters == []
    assert saved.total_outline.scale == accepted.scale.to_dict()
    assert saved.progress.target_words == 12_600
    assert saved.progress.current_volume == 1
    assert saved.progress.total_volumes == 1
    assert saved.progress.plan_status == "accepted"


@pytest.mark.asyncio
async def test_plan_version_conflict_and_tenant_isolation(
    repository, tenant_context, other_tenant_context, sample_novel
) -> None:
    tenant_id = str(tenant_context.tenant_id)
    other_id = str(other_tenant_context.tenant_id)
    novel_id = str(sample_novel.id)
    await repository.save(tenant_id, sample_novel)
    await repository.accept_plan(
        tenant_id,
        novel_id,
        _plan(),
        0,
        created_by_user_id=str(tenant_context.user_id),
        trigger_chapter=2,
        change_summary="调整第二卷节奏",
    )

    with pytest.raises(PlanVersionConflictError):
        await repository.accept_plan(tenant_id, novel_id, _plan(), 0)
    with pytest.raises(RuntimeError, match="目标小说不存在"):
        await repository.accept_plan(other_id, novel_id, _plan(), 0)

    assert await repository.get_latest_plan(other_id, novel_id) is None
    assert await repository.list_plan_versions(other_id, novel_id) == []
    assert [plan.version for plan in await repository.list_plan_versions(
        tenant_id, novel_id
    )] == [1]
    summaries = await repository.list_plan_version_summaries(tenant_id, novel_id)
    assert summaries[0].trigger_chapter == 2
    assert summaries[0].change_summary == "调整第二卷节奏"
    assert summaries[0].created_by_user_id == str(tenant_context.user_id)


@pytest.mark.asyncio
async def test_execution_upsert_rejects_stale_version_and_updates_progress(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id = str(tenant_context.tenant_id)
    novel_id = str(sample_novel.id)
    await repository.save(tenant_id, sample_novel)
    await repository.accept_plan(tenant_id, novel_id, _plan(), 0)
    await repository.accept_plan(tenant_id, novel_id, _plan(source="replan"), 1)

    with pytest.raises(PlanVersionConflictError):
        await repository.upsert_plan_execution(
            tenant_id, novel_id, PlanExecution(1, 1, "reconciled", 4200, {})
        )
    execution = PlanExecution(1, 2, "reconciled", 4200, {}, "major")
    await repository.upsert_plan_execution(tenant_id, novel_id, execution)

    saved = await repository.find_by_id(tenant_id, novel_id)
    records = await repository.list_plan_executions(tenant_id, novel_id)
    assert records == [execution]
    assert saved is not None and saved.progress.plan_status == "needs_review"
    assert saved.progress.drift_severity == "major"


@pytest.mark.asyncio
async def test_rewind_clears_executions_and_preserves_plan_mirror(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id = str(tenant_context.tenant_id)
    novel_id = str(sample_novel.id)
    await repository.save(tenant_id, sample_novel)
    await repository.accept_plan(tenant_id, novel_id, _plan(), 0)
    chapters: list[Chapter] = []
    for index in range(3):
        chapters.append(await _store_chapter(repository, tenant_id, novel_id, index))
        await repository.upsert_plan_execution(
            tenant_id, novel_id,
            PlanExecution(index + 1, 1, "reconciled", 4200, {}),
        )

    deleted, rewind_to = await repository.rewind_chapters_atomically(
        tenant_id, novel_id, [str(chapters[1].id)]
    )
    saved = await repository.find_by_id(tenant_id, novel_id)
    records = await repository.list_plan_executions(tenant_id, novel_id)

    assert (deleted, rewind_to) == (2, 1)
    assert [record.chapter_number for record in records] == [1]
    assert saved is not None and saved.progress.completed_words == 4200
    assert saved.progress.target_words == 12_600
    assert saved.progress.plan_version == 1
    assert saved.progress.plan_status == "needs_reconciliation"
    assert saved.progress.drift_severity == "minor"
