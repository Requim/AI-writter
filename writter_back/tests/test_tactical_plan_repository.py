"""PostgreSQL 战术版本仓储的原子、幂等与租户语义。"""

from dataclasses import replace

import pytest

from service.ports.tactical_plan_repository import TacticalPlanVersionConflictError
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    PlanExecution,
    ScaleContract,
    StoryArc,
    VolumePlan,
)
from service.value_objects.tactical_plan import TacticalBeat, TacticalWindow


def _plan(source: str = "initial") -> NovelPlan:
    slots = [
        ChapterSlot(
            number, "vol-1", ["main"], f"推进 {number}", ["事件"],
            "局势变化", 4200,
        )
        for number in range(1, 4)
    ]
    return NovelPlan(
        ScaleContract("custom", 3, 12_600), {"final_state": "闭合"},
        [VolumePlan(
            "vol-1", "第一卷", 1, 3, 12_600,
            "开场", "中点", "高潮", "退场",
        )],
        [StoryArc(
            "main", "main", 1, 3, "完成目标",
            [{"chapter_number": 2, "change": "升级"}], "目标完成", True,
        )],
        slots, source=source,
    )


def _beat(number: int) -> TacticalBeat:
    return TacticalBeat(
        number, f"ch{number}", "战术目标", "推进方法", "承接前章",
        "提高压力", "设置钩子", "张弛有度",
    )


def _window(
    plan_version: int = 1, story_revision: int = 0, start: int = 1,
) -> TacticalWindow:
    return TacticalWindow(
        plan_version, story_revision, start, 3, "vol-1", "完成窗口目标",
        [_beat(number) for number in range(start, 4)],
    )


async def _prepare(repository, tenant_id: str, novel, plan=None) -> NovelPlan:
    await repository.save(tenant_id, novel)
    return await repository.accept_plan(
        tenant_id, str(novel.id), plan or _plan(), 0,
        idempotency_key="tactical-test-plan-initial",
    )


@pytest.mark.asyncio
async def test_tactical_accept_is_append_only_and_retry_idempotent(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id, novel_id = str(tenant_context.tenant_id), str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    candidate = _window(plan.version)

    accepted = await repository.accept_tactical_plan(
        tenant_id, novel_id, candidate, 0,
        idempotency_key="proposal-initial",
        created_by_user_id=str(tenant_context.user_id),
    )
    retried = await repository.accept_tactical_plan(
        tenant_id, novel_id, candidate, 0,
        idempotency_key="proposal-initial",
        created_by_user_id=str(tenant_context.user_id),
    )
    versions = await repository.list_tactical_plan_versions(tenant_id, novel_id)

    assert accepted.version == retried.version == 1
    assert candidate.version == 0
    assert [window.version for window in versions] == [1]


@pytest.mark.asyncio
async def test_rewind_can_append_same_revision_with_new_proposal_key(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id, novel_id = str(tenant_context.tenant_id), str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    candidate = _window(plan.version)
    first = await repository.accept_tactical_plan(
        tenant_id, novel_id, candidate, 0,
        idempotency_key="proposal-before-rewind",
    )

    revised = replace(candidate, window_objective="回退后重新生成的窗口目标")
    second = await repository.accept_tactical_plan(
        tenant_id, novel_id, revised, first.version,
        idempotency_key="proposal-after-rewind",
    )
    versions = await repository.list_tactical_plan_versions(tenant_id, novel_id)

    assert second.version == 2
    assert second.story_state_revision == first.story_state_revision
    assert second.start_chapter == first.start_chapter
    assert [window.version for window in versions] == [2, 1]


@pytest.mark.asyncio
async def test_tactical_accept_detects_version_and_idempotency_conflicts(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id, novel_id = str(tenant_context.tenant_id), str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    candidate = _window(plan.version)
    await repository.accept_tactical_plan(
        tenant_id, novel_id, candidate, 0,
        idempotency_key="proposal-conflict",
    )

    with pytest.raises(TacticalPlanVersionConflictError, match="幂等键"):
        await repository.accept_tactical_plan(
            tenant_id, novel_id,
            replace(candidate, window_objective="不同内容"), 0,
            idempotency_key="proposal-conflict",
        )
    with pytest.raises(TacticalPlanVersionConflictError, match="已更新"):
        await repository.accept_tactical_plan(
            tenant_id, novel_id, _window(plan.version, 1, 2), 0,
            idempotency_key="proposal-stale-version",
        )


@pytest.mark.asyncio
async def test_tactical_repository_is_tenant_isolated_and_replan_invalidates(
    repository, tenant_context, other_tenant_context, sample_novel
) -> None:
    tenant_id = str(tenant_context.tenant_id)
    other_id = str(other_tenant_context.tenant_id)
    novel_id = str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    await repository.accept_tactical_plan(
        tenant_id, novel_id, _window(plan.version), 0,
        idempotency_key="proposal-tenant-isolation",
    )

    assert await repository.get_latest_tactical_plan(other_id, novel_id) is None
    assert await repository.list_tactical_plan_versions(other_id, novel_id) == []
    await repository.accept_plan(
        tenant_id, novel_id, _plan("replan"), 1,
        idempotency_key="tactical-test-plan-replan",
    )
    with pytest.raises(TacticalPlanVersionConflictError, match="整书计划"):
        await repository.accept_tactical_plan(
            tenant_id, novel_id, _window(plan.version, 1, 2), 1,
            idempotency_key="proposal-after-replan",
        )


@pytest.mark.asyncio
async def test_execution_links_accepted_tactical_version_and_cascade_delete(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id, novel_id = str(tenant_context.tenant_id), str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    tactical = await repository.accept_tactical_plan(
        tenant_id, novel_id, _window(plan.version), 0,
        idempotency_key="proposal-execution-link",
    )
    execution = PlanExecution(
        1, plan.version, "reconciled", 4200, {},
        tactical_version=tactical.version,
    )

    await repository.upsert_plan_execution(tenant_id, novel_id, execution)
    assert (await repository.list_plan_executions(
        tenant_id, novel_id
    ))[0].tactical_version == tactical.version
    await repository.delete(tenant_id, novel_id)
    assert await repository.get_latest_tactical_plan(tenant_id, novel_id) is None


@pytest.mark.asyncio
async def test_execution_rejects_tactical_window_outside_chapter(
    repository, tenant_context, sample_novel
) -> None:
    tenant_id, novel_id = str(tenant_context.tenant_id), str(sample_novel.id)
    plan = await _prepare(repository, tenant_id, sample_novel)
    tactical = await repository.accept_tactical_plan(
        tenant_id, novel_id, _window(plan.version, 1, 2), 0,
        idempotency_key="proposal-window-starts-at-two",
    )
    execution = PlanExecution(
        1, plan.version, "reconciled", 4200, {},
        tactical_version=tactical.version,
    )

    with pytest.raises(TacticalPlanVersionConflictError, match="未覆盖第 1 章"):
        await repository.upsert_plan_execution(tenant_id, novel_id, execution)
