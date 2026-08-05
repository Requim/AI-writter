"""额度流水与章节质量元数据持久化测试。"""

from datetime import datetime
from uuid import uuid4

import pytest

from api.routers.novel_router import _chapter_response, _chapter_summary_response
from api.routers.tenant_router import current_period_start, current_usage
from application.agents.persist_node import _chapter_entity, _completed_chapter
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.database.models import TenantModel
from service.entities.chapter import Chapter
from service.entities.identity import TenantContext


class FakeUsageRepository:
    async def quota_usage_details(self, _tenant_id, _period_start):
        return {
            "breakdown": {"outline": 1, "chapter": 3, "rewrite": 1, "other": 2},
            "recent": [{"operation_type": "chapter", "chapter_index": 2}],
        }


@pytest.mark.asyncio
async def test_current_usage_includes_breakdown_and_recent():
    context = TenantContext(
        tenant_id=uuid4(), tenant_name="额度测试租户", user_id=uuid4(),
        role="owner", is_platform_admin=False, ai_enabled=True,
        monthly_generation_limit=10,
    )

    result = await current_usage(context, FakeUsageRepository())

    assert result["used"] == 7
    assert result["remaining"] == 3
    assert result["unlimited"] is False
    assert result["breakdown"] == {
        "outline": 1, "chapter": 3, "rewrite": 1, "other": 2,
    }
    assert result["recent"][0]["chapter_index"] == 2


@pytest.mark.asyncio
async def test_quota_retry_reuses_exact_ledger_key(repository, tenant_context):
    identity = IdentityRepository(repository.async_session)
    run_id = uuid4()
    period_start = current_period_start()

    first = await identity.reserve_quota(
        tenant_context, run_id, "chapter", 2, period_start,
    )
    retry = await identity.reserve_quota(
        tenant_context, run_id, "chapter", 2, period_start,
    )
    second = await identity.reserve_quota(
        tenant_context, run_id, "rewrite", 2, period_start,
    )
    details = await identity.quota_usage_details(tenant_context.tenant_id, period_start)

    assert first[0] == retry[0] == 1
    assert second[0] == 2
    assert details["breakdown"] == {
        "outline": 0, "chapter": 1, "rewrite": 1, "other": 0,
    }
    assert len(details["recent"]) == 2


@pytest.mark.asyncio
async def test_unlimited_quota_still_records_usage(repository, tenant_context):
    identity = IdentityRepository(repository.async_session)
    period_start = current_period_start()
    async with repository.async_session() as session, session.begin():
        tenant = await session.get(TenantModel, tenant_context.tenant_id)
        tenant.monthly_generation_unlimited = True
        tenant.monthly_generation_limit = 0

    first = await identity.reserve_quota(
        tenant_context, uuid4(), "outline", -1, period_start,
    )
    second = await identity.reserve_quota(
        tenant_context, uuid4(), "chapter", 0, period_start,
    )

    assert first[0] == 1
    assert second[0] == 2


@pytest.mark.asyncio
async def test_current_usage_marks_unlimited_quota():
    context = TenantContext(
        tenant_id=uuid4(), tenant_name="无限额度租户", user_id=uuid4(),
        role="owner", is_platform_admin=False, ai_enabled=True,
        monthly_generation_limit=2_147_483_647,
        monthly_generation_unlimited=True,
    )

    result = await current_usage(context, FakeUsageRepository())

    assert result["unlimited"] is True
    assert result["used"] == 7


def test_persisted_chapter_contains_quality_metadata():
    novel_id = str(uuid4())
    state = {
        "chapter_outlines": [{"title": "审读后的章节"}],
        "quality_gate": {
            "decision": "user_accepted_revision",
            "score": 0.76,
            "source_score_scale": 100,
            "prompt_version": "quality-v3",
        },
        "reflection_issues": [{"type": "continuity", "description": "线索过早"}],
        "user_decision": {"action": "accept"},
        "revision_attempts": 2,
        "revision_history": [{"attempt": 1}, {"attempt": 2}],
    }

    completed = _completed_chapter(state, "章节正文", 2)
    chapter = _chapter_entity(completed, novel_id)

    assert chapter.reflection_issues == state["reflection_issues"]
    assert chapter.revision_count == 2
    assert chapter.revision_history == state["revision_history"]
    assert chapter.user_decision == {
        "action": "accept",
        "review_status": "accepted_with_issues",
        "quality_score": 0.76,
        "source_score_scale": 100,
        "prompt_version": "quality-v3",
    }


@pytest.mark.parametrize(
    ("decision", "expected_status", "expected_score"),
    [
        ({"review_status": "passed", "quality_score": 0.9}, "passed", 0.9),
        ({"review_status": "pass", "quality_score": 0.9}, "passed", 0.9),
        ({"review_status": "accepted_unreviewed"}, "accepted_unreviewed", None),
        ({"review_status": "obsolete", "quality_score": True}, "unknown", None),
        (None, "unknown", None),
    ],
)
def test_chapter_responses_expose_compatible_review_status(
    decision, expected_status, expected_score,
):
    chapter = Chapter(
        novel_id=uuid4(), title="第一章", content="正文", word_count=2,
        status="completed", updated_at=datetime.now(), user_decision=decision,
    )

    summary = _chapter_summary_response(chapter)
    detail = _chapter_response(chapter)

    assert summary.review_status == expected_status
    assert summary.quality_score == expected_score
    assert detail.review_status == expected_status
    assert detail.quality_score == expected_score
