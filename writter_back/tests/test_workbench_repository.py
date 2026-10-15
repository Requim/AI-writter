"""Exercise persisted CAS, scope filters and idempotency on isolated PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest


async def setup_workbench(repository, tenant_context, sample_novel):
    from infrastructure.database.workbench_repository import WorkbenchRepository
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    return WorkbenchRepository(repository.async_session), str(tenant_context.tenant_id), str(sample_novel.id)


@pytest.mark.asyncio
async def test_assets_are_versioned_and_copy_is_independent(repository, tenant_context, sample_novel):
    from application.workbench.contracts import AssetInput, AssetEdit, WorkbenchConflict
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    original = await wb.save_asset(tenant, novel, AssetInput(title="师父", kind="character", content="曾经失明"))
    edited = await wb.edit_asset(tenant, novel, original["id"], AssetEdit(
        title="师父", kind="character", content="仍然失明", expected_version=1,
    ))
    assert edited["version"] == 2
    assert [row["content"] for row in await wb.asset_versions(tenant, novel, original["id"])] == ["仍然失明", "曾经失明"]
    with pytest.raises(WorkbenchConflict):
        await wb.edit_asset(tenant, novel, original["id"], AssetEdit(
            title="师父", kind="character", content="错误覆盖", expected_version=1,
        ))
    from service.entities.novel import Novel
    target = Novel(tenant_id=tenant_context.tenant_id, user_id=tenant_context.user_id, novel_type="fantasy", title="另一作品")
    await repository.save(tenant, target)
    copied = await wb.save_asset(tenant, str(target.id), AssetInput(
        title=edited["title"], kind=edited["kind"], content=edited["content"],
    ), {"source_asset_id": original["id"], "source_version": 2})
    await wb.edit_asset(tenant, novel, original["id"], AssetEdit(
        title="师父", kind="character", content="恢复视力", expected_version=2,
    ))
    assert (await wb.asset(tenant, str(target.id), copied["id"]))["content"] == "仍然失明"


@pytest.mark.asyncio
async def test_draft_not_implicitly_retrieved_and_other_tenant_cannot_read(repository, tenant_context, other_tenant_context, sample_novel):
    from application.workbench.contracts import AssetInput
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    draft = await wb.save_asset(tenant, novel, AssetInput(title="废稿", kind="chapter", content="青玉剑已经毁坏。"))
    setting = await wb.save_asset(tenant, novel, AssetInput(title="青玉剑", kind="world", content="青玉剑不可损毁。"))
    hits = await wb.search(tenant, novel, "青玉剑")
    assert any(row["source_id"] == setting["id"] for row in hits)
    assert all(row["source_id"] != draft["id"] for row in hits)
    assert await wb.assets(str(other_tenant_context.tenant_id), novel) == []
    assert await wb.search(str(other_tenant_context.tenant_id), novel, "青玉剑") == []


@pytest.mark.asyncio
async def test_message_command_replays_without_duplicate_messages(repository, tenant_context, sample_novel):
    from application.workbench.contracts import MessageInput, WorkbenchConflict
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    conversation = await wb.create_conversation(tenant, novel, "构思")
    command = MessageInput(text="师父为何失明？", intent="discuss")
    job, created = await wb.create_job(tenant, novel, conversation["id"], command, "same", {})
    replay, again = await wb.create_job(tenant, novel, conversation["id"], command, "same", {})
    assert created and not again and replay["id"] == job["id"]
    assert len((await wb.conversation(tenant, novel, conversation["id"]))["messages"]) == 2
    with pytest.raises(WorkbenchConflict):
        await wb.create_job(tenant, novel, conversation["id"], MessageInput(text="另一请求"), "same", {})
    assert await wb.job(str(uuid4()), novel, job["id"]) is None


@pytest.mark.asyncio
async def test_adoption_is_explicit_atomic_and_idempotent(repository, tenant_context, sample_novel):
    from application.workbench.contracts import AdoptInput, AssetInput, WorkbenchConflict
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    asset = await wb.save_asset(tenant, novel, AssetInput(title="归还", kind="chapter", content="师父归还青玉剑。"))
    assert (await repository.find_by_id_with_chapters(tenant, novel)).chapters == []
    prepared = {
        "basis": await wb.basis(tenant, novel), "summary": "师父归还青玉剑",
        "story_state": '{"immutable_facts":["剑已归还"]}',
        "memory_content": "师父归还青玉剑。", "memory_metadata": {"type": "chapter", "chapter_index": 0},
    }
    with pytest.raises(WorkbenchConflict, match="审读"):
        await wb.adopt(tenant, novel, asset["id"], AdoptInput(expected_version=1), prepared)
    command = AdoptInput(expected_version=1, acceptance="unreviewed")
    first = await wb.adopt(tenant, novel, asset["id"], command, prepared)
    again = await wb.adopt(tenant, novel, asset["id"], command, prepared)
    assert again == first
    value = await repository.find_by_id_with_chapters(tenant, novel)
    assert len(value.chapters) == 1 and value.progress.current_chapter == 1
    assert value.chapters[0].content == "师父归还青玉剑。"
    assert value.chapters[0].user_decision["review_status"] == "accepted_unreviewed"
    hits = await wb.search(tenant, novel, "青玉剑")
    assert any(hit["source_type"] == "chapter" for hit in hits)


@pytest.mark.asyncio
async def test_changed_settings_block_stale_adoption(repository, tenant_context, sample_novel):
    from application.workbench.contracts import AdoptInput, AssetInput, WorkbenchConflict
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    asset = await wb.save_asset(tenant, novel, AssetInput(title="归还", kind="chapter", content="师父归还青玉剑。"))
    basis = await wb.basis(tenant, novel)
    await wb.save_asset(tenant, novel, AssetInput(title="禁区", kind="world", content="青玉剑早已毁坏。"))
    with pytest.raises(WorkbenchConflict, match="变化"):
        await wb.adopt(tenant, novel, asset["id"], AdoptInput(expected_version=1, acceptance="unreviewed"), {"basis": basis})
    assert (await repository.find_by_id_with_chapters(tenant, novel)).chapters == []


@pytest.mark.asyncio
async def test_original_editor_updates_and_rewind_remove_old_retrieval(repository, tenant_context, sample_novel):
    from service.entities.chapter import Chapter
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    chapter = Chapter(novel_id=sample_novel.id, content="师父归还青玉剑。", title="承诺", status="completed")
    await repository.save_chapter(tenant, novel, chapter)
    assert await wb.search(tenant, novel, "青玉剑")
    chapter.content = "师父归还长刀。"
    await repository.update_chapter_consistently(tenant, novel, chapter, 1, chapter.content, {"type": "chapter", "chapter_index": 0}, "归还长刀")
    assert await wb.search(tenant, novel, "青玉剑") == []
    hits = await wb.search(tenant, novel, "长刀")
    assert hits and all(hit["version"] == 2 for hit in hits)
    await repository.rewind_chapters_atomically(tenant, novel, [str(chapter.id)])
    assert await wb.search(tenant, novel, "长刀") == []


@pytest.mark.asyncio
async def test_only_current_official_chapters_are_searchable(repository, tenant_context, sample_novel):
    from service.entities.chapter import Chapter
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    chapter = Chapter(novel_id=sample_novel.id, content="未定稿的青玉剑。", title="候选", status="draft")
    await repository.save_chapter(tenant, novel, chapter)
    assert await wb.search(tenant, novel, "青玉剑") == []


@pytest.mark.asyncio
async def test_existing_sources_backfill_once_without_rewriting_current_chunks(repository, tenant_context, sample_novel):
    from sqlalchemy import delete, select
    from infrastructure.database.workbench_models import SourceChunkModel
    from service.entities.chapter import Chapter
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    chapter = Chapter(novel_id=sample_novel.id, content="师父归还青玉剑。", title="旧作品", status="completed")
    await repository.save_chapter(tenant, novel, chapter)
    async with repository.async_session() as session:
        before = set((await session.scalars(select(SourceChunkModel.id))).all())
    assert await wb.ensure_index(tenant, novel) is False
    async with repository.async_session() as session:
        assert set((await session.scalars(select(SourceChunkModel.id))).all()) == before
        async with session.begin_nested():
            await session.execute(delete(SourceChunkModel).where(SourceChunkModel.novel_id == sample_novel.id))
        await session.commit()
    assert await wb.ensure_index(tenant, novel) is True
    assert await wb.search(tenant, novel, "青玉剑")
    assert await wb.ensure_index(tenant, novel) is False


@pytest.mark.asyncio
async def test_degraded_retrieval_and_partial_attempts_are_public(repository, tenant_context, sample_novel):
    from application.workbench.contracts import MessageInput
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    conversation = await wb.create_conversation(tenant, novel, "恢复")
    snapshot = {"retrieval_available": False, "previous_attempts": [{"content": "未完成正文", "status": "failed"}]}
    job, _ = await wb.create_job(tenant, novel, conversation["id"], MessageInput(text="续写"), "recover", snapshot)
    assert job["retrieval_available"] is False
    assert job["previous_attempts"][0]["content"] == "未完成正文"
    messages = (await wb.conversation(tenant, novel, conversation["id"]))["messages"]
    assistant = next(row for row in messages if row["role"] == "assistant")
    assert assistant["retrieval_available"] is False
    assert assistant["previous_attempts"][0]["content"] == "未完成正文"


@pytest.mark.asyncio
async def test_concurrent_retries_queue_one_attempt_and_keep_partial(repository, tenant_context, sample_novel):
    from application.workbench.contracts import MessageInput
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    conversation = await wb.create_conversation(tenant, novel, "重试")
    job, _ = await wb.create_job(tenant, novel, conversation["id"], MessageInput(text="写正文"), "once",
                                 {"basis": await wb.basis(tenant, novel)})
    await wb.update_job(tenant, novel, job["id"], status="failed", content="已保留的段落")
    results = await asyncio.gather(*(wb.retry_job(tenant, novel, job["id"]) for _ in range(2)))
    assert sum(created for _, created in results) == 1
    current = await wb.job(tenant, novel, job["id"])
    assert current["status"] == "queued"
    assert current["previous_attempts"] == [{"content": "已保留的段落", "status": "failed"}]


@pytest.mark.asyncio
async def test_replacement_adoption_updates_official_state_progress_and_memories(repository, tenant_context, sample_novel):
    from sqlalchemy import select
    from application.workbench.contracts import AdoptInput, AssetInput
    from infrastructure.database.models import MemoryModel
    from service.entities.chapter import Chapter
    wb, tenant, novel = await setup_workbench(repository, tenant_context, sample_novel)
    target = Chapter(novel_id=sample_novel.id, title="旧章", content="旧稿", status="draft")
    await repository.save_chapter(tenant, novel, target)
    asset = await wb.save_asset(tenant, novel, AssetInput(title="归还", kind="chapter", content="师父归还了青玉剑。"))
    basis = await wb.basis(tenant, novel)
    issues = [{"description": "暂留的节奏问题", "severity": "low"}]
    await wb.set_review(tenant, novel, asset["id"], 1, {"asset_version": 1, "basis": basis, "gate": {"decision": "patch"}, "issues": issues})
    prepared = {"basis": basis, "summary": "剑已归还", "story_state": '{"immutable_facts":["剑已归还"]}',
                "memory_content": asset["content"], "memory_metadata": {"type": "chapter", "chapter_index": 0}}
    command = AdoptInput(expected_version=1, acceptance="with_issues", target_chapter_id=target.id, expected_chapter_version=1)
    receipt = await wb.adopt(tenant, novel, asset["id"], command, prepared)
    value = await repository.find_by_id_with_chapters(tenant, novel)
    assert value.chapters[0].status == "completed" and value.chapters[0].reflection_issues == issues
    assert value.progress.completed_words == len(asset["content"])
    assert value.progress.current_chapter == 1
    assert receipt["chapter_version"] == 2
    assert await wb.search(tenant, novel, "青玉剑")
    async with repository.async_session() as session:
        memories = (await session.scalars(select(MemoryModel).where(MemoryModel.novel_id == sample_novel.id))).all()
    assert any(row.meta_data.get("type") == "story_state" and row.content == prepared["story_state"] for row in memories)
