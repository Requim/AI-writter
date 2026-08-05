"""整书规划 API 边界与兼容镜像测试。"""

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.routers.novel_router import (
    NovelCreateRequest,
    _creation_outline_and_progress,
    _optional_latest_plan,
    _plan_version_payloads,
    _progress_response,
    get_novel_plan,
    get_tactical_plan,
    list_tactical_plan_versions,
)
from service.entities.identity import TenantContext
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    PlanExecution,
    ScaleContract,
    StoryArc,
    VolumePlan,
)
from service.value_objects.progress import Progress
from service.value_objects.tactical_plan import TacticalBeat, TacticalWindow


def _plan() -> NovelPlan:
    chapters = 12
    return NovelPlan(
        scale=ScaleContract("short", chapters, 50_400),
        ending_contract={"final_state": "真相公开"},
        volumes=[VolumePlan(
            "volume-1", "第一卷", 1, chapters, 50_400,
            opening_state="危机出现", midpoint_turn="认知逆转",
            climax="真相对峙", ending_state="代价落定",
        )],
        arcs=[StoryArc(
            "arc-main", "主线", 1, chapters, "查明真相",
            [{"chapter_number": 6, "change": "证人改口"}], "最终章公开证据", True,
        )],
        chapter_slots=[ChapterSlot(
            number, "volume-1", ["arc-main"], f"推进第 {number} 章",
            ["验证线索"], "认知变化", 4_200,
        ) for number in range(1, chapters + 1)],
        version=3,
    )


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(), tenant_name="测试租户", user_id=uuid4(),
        role="owner", is_platform_admin=False, ai_enabled=True,
        monthly_generation_limit=30,
    )


def _tactical() -> TacticalWindow:
    return TacticalWindow(
        novel_plan_version=3,
        story_state_revision=0,
        start_chapter=1,
        end_chapter=6,
        volume_id="volume-1",
        window_objective="确认第一批证据",
        beats=[TacticalBeat(
            number, f"ch{number}", f"推进 {number}", "核验证据",
            "承接现状", "对手反制", "发现新目标", "逐步加压",
        ) for number in range(1, 7)],
        version=2,
    )


def test_new_and_legacy_create_requests_share_scale_contract() -> None:
    request = NovelCreateRequest(
        novel_type="suspense",
        planning={
            "preset": "medium", "target_chapters": 36,
            "target_total_words": 151_200,
        },
        total_outline={"total_chapters": 12, "writing_style": "冷峻"},
    )
    outline, progress = _creation_outline_and_progress(request)
    assert outline is not None and outline.total_chapters == 36
    assert outline.scale["target_total_words"] == 151_200
    assert progress.total_chapters == 36 and progress.plan_status == "pending"

    legacy = NovelCreateRequest(
        novel_type="suspense", total_outline={"total_chapters": 10},
    )
    legacy_outline, legacy_progress = _creation_outline_and_progress(legacy)
    assert legacy_outline is not None and legacy_outline.scale["preset"] == "custom"
    assert legacy_progress.target_words == 42_000


def test_create_request_rejects_impossible_word_budget() -> None:
    with pytest.raises(ValidationError, match="目标总字数"):
        NovelCreateRequest(
            novel_type="suspense",
            planning={
                "preset": "custom", "target_chapters": 12,
                "target_total_words": 20_000,
            },
        )


def test_progress_uses_accepted_plan_as_authority() -> None:
    progress = Progress(
        current_chapter=2, total_chapters=99, percentage=2.0,
        target_words=999_999, completed_words=8_400,
        plan_version=3, plan_status="needs_review", drift_severity="major",
    )
    response = _progress_response(progress, _plan())

    assert response.total_chapters == 12
    assert response.chapter_progress["total"] == 12
    assert response.word_progress["target"] == 50_400
    assert response.plan_status == "needs_review"
    assert response.drift_severity == "major"


@pytest.mark.asyncio
async def test_plan_loading_is_separate_and_includes_executions() -> None:
    plan = _plan()
    execution = PlanExecution(1, 3, "fulfilled", 4_200, {})
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=object()),
        get_latest_plan=AsyncMock(return_value=plan),
        list_plan_executions=AsyncMock(return_value=[execution]),
    )
    payload = await get_novel_plan("novel-1", _context(), repository)

    assert payload["version"] == 3
    assert len(payload["chapter_slots"]) == 12
    assert payload["executions"][0]["chapter_number"] == 1


@pytest.mark.asyncio
async def test_version_list_and_sync_repository_compatibility() -> None:
    plan = _plan()
    plan.created_at = datetime(2026, 8, 5, tzinfo=timezone.utc)
    repository = SimpleNamespace(
        list_plan_versions=AsyncMock(return_value=[plan]),
        get_latest_plan=lambda *_args: plan,
    )
    versions = await _plan_version_payloads(repository, "tenant-1", "novel-1")

    assert versions[0]["version"] == 3
    assert versions[0]["trigger_chapter"] is None
    assert await _optional_latest_plan(repository, "tenant-1", "novel-1") is plan


@pytest.mark.asyncio
async def test_tactical_plan_loads_separately_with_hydrated_contracts() -> None:
    plan, tactical = _plan(), _tactical()
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(progress=Progress())),
        get_latest_plan=AsyncMock(return_value=plan),
        get_latest_tactical_plan=AsyncMock(return_value=tactical),
    )
    payload = await get_tactical_plan("novel-1", _context(), repository)

    assert payload["status"] == "active"
    assert payload["window"]["version"] == 2
    assert payload["assembled_slots"][0]["tactical"]["slot_ref"] == "ch1"
    assert payload["assembled_slots"][0]["slot_contract"]["target_words"] == 4200


@pytest.mark.asyncio
async def test_stale_tactical_plan_is_not_hydrated_with_latest_plan() -> None:
    plan = _plan()
    stale = replace(_tactical(), novel_plan_version=plan.version - 1)
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(progress=Progress())),
        get_latest_plan=AsyncMock(return_value=plan),
        get_latest_tactical_plan=AsyncMock(return_value=stale),
    )

    payload = await get_tactical_plan("novel-1", _context(), repository)

    assert payload["status"] == "stale"
    assert payload["window"]["novel_plan_version"] == plan.version - 1
    assert payload["assembled_slots"] == []


@pytest.mark.asyncio
async def test_tactical_history_returns_lightweight_summaries() -> None:
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=object()),
        list_tactical_plan_versions=AsyncMock(return_value=[_tactical()]),
    )
    versions = await list_tactical_plan_versions(
        "novel-1", _context(), repository
    )
    assert versions[0]["version"] == 2
    assert "beats" not in versions[0]


def test_progress_marks_tactical_stale_after_rewind() -> None:
    progress = Progress(
        current_chapter=0,
        total_chapters=12,
        plan_status="needs_reconciliation",
    )
    response = _progress_response(progress, _plan(), _tactical())
    assert response.tactical_version == 2
    assert response.tactical_status == "stale"
