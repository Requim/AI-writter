"""真实章节归档事务验证事实版本门禁及手工修改失效。"""
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from application.fact_archive_guard import archive_fact_guard
from application.fact_evaluation import evaluate_facts
from infrastructure.database.models import ChapterModel, MemoryModel
from infrastructure.database.repository import _edited_fact_metadata
from service.entities.chapter import Chapter
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.fact_gate import FactGateBlockedError
from service.value_objects.progress import Progress
from service.value_objects.story_fact import StoryEntity
from tests.test_chapter_constraints_repository import ledger  # noqa: F401


@pytest.mark.asyncio
async def test_stale_fact_guard_preserves_previous_chapter_and_memory(repository, ledger):  # noqa: F811
    store, tenant, novel = ledger
    old = Chapter(id=uuid4(), novel_id=UUID(novel), chapter_index=0, title="旧稿", content="旧正文", word_count=3)
    await repository.replace_chapter(tenant, novel, old, "旧记忆", {}, Progress(current_chapter=1))
    snapshot = await store.capture_constraints(tenant, novel, 1)
    content = "新正文"
    report = await evaluate_facts(snapshot, content, "body", None)
    ack = {"report_digest": report.digest, "reviewed_by": "tester", "proposal_id": "current"}
    guard = archive_fact_guard(store, tenant, novel, snapshot, report, ack)
    await store.ensure_entity(tenant, novel, StoryEntity(entity_key="changed", kind="character", name="辛远"))
    new = Chapter(id=uuid4(), novel_id=UUID(novel), chapter_index=0, title="新稿", content=content, word_count=3)
    with pytest.raises(FactVersionConflictError):
        await repository.replace_chapter(tenant, novel, new, "新记忆", {}, Progress(current_chapter=1), fact_guard=guard)
    async with repository.async_session() as session:
        chapters = list((await session.scalars(select(ChapterModel))).all())
        memories = list((await session.scalars(select(MemoryModel))).all())
    assert len(chapters) == 1 and chapters[0].id == old.id
    assert any(item.content == "旧记忆" for item in memories)
    assert not any(item.content == "新记忆" for item in memories)


@pytest.mark.asyncio
async def test_receipt_without_transaction_guard_is_rejected(repository, ledger):  # noqa: F811
    _, tenant, novel = ledger
    chapter = Chapter(id=uuid4(), novel_id=UUID(novel), chapter_index=0, title="稿件", content="正文", word_count=2,
        user_decision={"fact_gate": {"status": "pass"}})
    with pytest.raises(FactGateBlockedError):
        await repository.replace_chapter(tenant, novel, chapter, "记忆", {}, Progress())
    async with repository.async_session() as session:
        assert list(await session.scalars(select(ChapterModel))) == []


def test_manual_edit_invalidates_pass_receipt_without_mutating_original():
    original = {"fact_gate": {"status": "pass"}, "fact_review": {}, "fact_input": {}, "action": "accept"}
    result = _edited_fact_metadata(SimpleNamespace(user_decision=original))
    assert result == {"action": "accept", "fact_validation_status": "manual_edit_unverified"}
    assert "fact_gate" in original
