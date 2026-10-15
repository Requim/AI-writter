"""Tenant-scoped persistence; derived text indexes share source write transactions."""

import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import delete, func, or_, select, text

from application.workbench.contracts import WorkbenchConflict
from application.workbench.retrieval import chunk_text, query_terms, rank_sources
from infrastructure.database.models import ChapterModel, MemoryModel, utc_now
from infrastructure.database.repository import _lock_novel
from infrastructure.database.workbench_models import (
    AssetModel, AssetVersionModel, ConversationModel, JobModel, MessageModel, SourceChunkModel,
)

ACTIVE_KINDS = ("world", "character", "outline")
TERMINAL = ("completed", "failed", "stopped")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def payload(row) -> dict:
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.key)
        result[column.key] = str(value) if isinstance(value, UUID) else (value.isoformat() if hasattr(value, "isoformat") else value)
    return result


def scope(model, tenant, novel):
    return (model.tenant_id == UUID(str(tenant)), model.novel_id == UUID(str(novel)))


def job_payload(row, private=False):
    result = payload(row)
    result["retrieval_available"] = row.snapshot.get("retrieval_available", True)
    result["previous_attempts"] = row.snapshot.get("previous_attempts", [])
    if not private:
        for name in ("request", "snapshot", "command_digest", "command_key", "tenant_id", "novel_id"):
            result.pop(name, None)
    return result


async def index_source(session, tenant, novel, source_type, source_id, title, version, content, kind, chapter_index=None):
    await session.execute(delete(SourceChunkModel).where(
        *scope(SourceChunkModel, tenant, novel), SourceChunkModel.source_type == source_type,
        SourceChunkModel.source_id == UUID(str(source_id)),
    ))
    session.add_all([
        SourceChunkModel(
            tenant_id=UUID(str(tenant)), novel_id=UUID(str(novel)), source_type=source_type,
            source_id=UUID(str(source_id)), title=title or "未命名", version=version,
            kind=kind, chapter_index=chapter_index, **chunk,
        ) for chunk in chunk_text(content or "")
    ])


def add_version(session, asset):
    session.add(AssetVersionModel(
        tenant_id=asset.tenant_id, novel_id=asset.novel_id, asset_id=asset.id,
        version=asset.version, title=asset.title, kind=asset.kind, content=asset.content,
    ))


async def next_message_time(session, tenant, novel, conversation_id):
    latest = await session.scalar(select(func.max(MessageModel.created_at)).where(
        *scope(MessageModel, tenant, novel), MessageModel.conversation_id == conversation_id,
    ))
    now = utc_now()
    return max(now, latest + timedelta(microseconds=1)) if latest else now


async def message_provenance(session, tenant, novel, message_id, origin):
    if not message_id:
        return origin
    message = await session.scalar(select(MessageModel).where(*scope(MessageModel, tenant, novel), MessageModel.id == message_id))
    if message is None:
        raise LookupError("来源消息不存在")
    if not message.job_id:
        return origin
    job = await session.scalar(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.id == message.job_id))
    if job is None:
        return origin
    return {**origin, "job_id": str(job.id), "snapshot": job.snapshot, "chapter_index": job.chapter_index,
            "target_chapter_id": str(job.target_chapter_id) if job.target_chapter_id else None}


async def basis_in_session(session, tenant, novel, novel_row):
    chapters = (await session.scalars(select(ChapterModel).where(*scope(ChapterModel, tenant, novel)).order_by(ChapterModel.chapter_index))).all()
    assets = (await session.scalars(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.kind.in_(ACTIVE_KINDS)).order_by(AssetModel.id))).all()
    return digest({
        "outline": novel_row.total_outline, "title": novel_row.title, "summary": novel_row.summary,
        "chapters": [(str(row.id), row.version, row.chapter_index, digest(row.content)) for row in chapters],
        "assets": [(str(row.id), row.version) for row in assets],
    })


async def assert_snapshot_current(session, tenant, novel, novel_row, snapshot):
    if snapshot.get("basis") and snapshot["basis"] != await basis_in_session(session, tenant, novel, novel_row):
        raise WorkbenchConflict("作品或设定已变化，请重新发送")
    for asset_id, version in snapshot.get("references", []):
        source = await session.scalar(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.id == UUID(asset_id)))
        if source is None or source.version != version:
            raise WorkbenchConflict("引用资产已变化，请重新发送")


def validate_adoption_review(review, version, command, basis):
    review = review or {}
    if command.acceptance == "reviewed" and (
        review.get("asset_version") != version or review.get("gate", {}).get("decision") != "pass"
        or review.get("basis") != basis
    ):
        raise WorkbenchConflict("当前版本尚未通过审读，请重新审读或明确选择其他采纳方式")
    if command.acceptance == "with_issues" and (review.get("asset_version") != version or review.get("basis") != basis):
        raise WorkbenchConflict("带问题采纳需要当前版本的审读结果")


async def adoption_position(session, tenant, novel, command):
    chapters = (await session.scalars(select(ChapterModel).where(*scope(ChapterModel, tenant, novel)).order_by(ChapterModel.chapter_index))).all()
    if command.target_chapter_id:
        target = next((row for row in chapters if row.id == command.target_chapter_id), None)
        if target is None:
            raise LookupError("目标章节不存在")
        if command.expected_chapter_version != target.version:
            raise WorkbenchConflict("目标章节已修改，请重新载入")
        return target, target.chapter_index, chapters
    index = len(chapters)
    if any(row.chapter_index != i for i, row in enumerate(chapters)):
        raise WorkbenchConflict("章节目录不连续，请先修复现有目录")
    if command.chapter_index is not None and command.chapter_index != index:
        raise WorkbenchConflict("新章节只能按目录顺序追加")
    return None, index, chapters


async def append_adopted_chapter(session, tenant, novel, novel_row, chapter, chapters, prepared):
    from infrastructure.database.repository import _chapter_model, _add_continuity_memories, _checkpoint_sync_request
    session.add(_chapter_model(UUID(tenant), UUID(novel), chapter))
    await session.execute(delete(MemoryModel).where(*scope(MemoryModel, tenant, novel), MemoryModel.meta_data["type"].astext.in_(("story_state", "rolling_plan"))))
    _add_continuity_memories(
        session, UUID(tenant), UUID(novel), chapter, prepared["memory_content"], prepared["memory_metadata"],
        prepared["summary"], prepared["story_state"], None,
    )
    update_adopted_progress(novel_row, [*chapters, chapter])
    completed = chapter.chapter_index + 1
    progress = dict(novel_row.progress)
    progress["checkpoint_sync"] = _checkpoint_sync_request(completed, completed, progress["status"] == "completed")
    novel_row.progress = progress


def update_adopted_progress(novel_row, chapters):
    progress = dict(novel_row.progress or {})
    official = [row for row in chapters if row.status in ("completed", "revised")]
    completed = 0
    for row in sorted(official, key=lambda item: item.chapter_index):
        if row.chapter_index != completed:
            break
        completed += 1
    total, target_words = int(progress.get("total_chapters") or 0), int(progress.get("target_words") or 0)
    words = sum(len(row.content or "") for row in official)
    progress.update(current_chapter=completed, percentage=completed / total * 100 if total else 0,
                    status="completed" if total and completed >= total else "writing",
                    completed_words=words, word_percentage=words / target_words * 100 if target_words else 0)
    novel_row.progress, novel_row.status, novel_row.updated_at = progress, progress["status"], utc_now().replace(tzinfo=None)


async def replace_adopted_chapter(session, tenant, novel, novel_row, target, chapter, chapters, prepared):
    from infrastructure.database.repository import (
        _delete_plan_executions, _mark_edit_checkpoint_sync, _replace_edited_memories, _update_chapter_row,
    )
    if not await _update_chapter_row(session, UUID(tenant), UUID(novel), chapter, target.version):
        raise WorkbenchConflict("目标章节版本冲突")
    target.status, target.reflection_issues = chapter.status, chapter.reflection_issues
    await _replace_edited_memories(session, UUID(tenant), UUID(novel), chapter, prepared["memory_content"], prepared["memory_metadata"], prepared["summary"])
    session.add(MemoryModel(
        tenant_id=UUID(tenant), novel_id=UUID(novel), content=prepared["story_state"],
        meta_data={"type": "story_state", "chapter_index": chapter.chapter_index},
    ))
    await _delete_plan_executions(session, UUID(tenant), UUID(novel), chapter.chapter_index + 1, from_chapter=False)
    update_adopted_progress(novel_row, chapters)
    _mark_edit_checkpoint_sync(novel_row, chapter.updated_at)


class WorkbenchRepository:
    def __init__(self, async_session):
        self.async_session = async_session

    async def conversations(self, tenant, novel):
        async with self.async_session() as session:
            rows = (await session.scalars(select(ConversationModel).where(*scope(ConversationModel, tenant, novel)).order_by(ConversationModel.updated_at.desc()))).all()
            return [payload(row) for row in rows]

    async def create_conversation(self, tenant, novel, title):
        async with self.async_session() as session, session.begin():
            if await _lock_novel(session, UUID(tenant), UUID(novel)) is None:
                raise LookupError("作品不存在")
            row = ConversationModel(id=uuid4(), tenant_id=UUID(tenant), novel_id=UUID(novel), title=title or "新对话", created_at=utc_now(), updated_at=utc_now())
            session.add(row)
            await session.flush()
            return payload(row)

    async def conversation(self, tenant, novel, conversation_id):
        async with self.async_session() as session:
            row = await session.scalar(select(ConversationModel).where(*scope(ConversationModel, tenant, novel), ConversationModel.id == UUID(conversation_id)))
            if row is None:
                return None
            messages = (await session.scalars(select(MessageModel).where(*scope(MessageModel, tenant, novel), MessageModel.conversation_id == row.id).order_by(MessageModel.created_at, MessageModel.role.desc(), MessageModel.id))).all()
            jobs = (await session.scalars(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.conversation_id == row.id))).all()
            by_job = {item.id: item for item in jobs}
            result = []
            for item in messages:
                value = payload(item)
                job = by_job.get(item.job_id)
                if job:
                    value["retrieval_available"] = job.snapshot.get("retrieval_available", True)
                    value["previous_attempts"] = job.snapshot.get("previous_attempts", [])
                result.append(value)
            return {"conversation": payload(row), "messages": result}

    async def rename_conversation(self, tenant, novel, conversation_id, title):
        async with self.async_session() as session, session.begin():
            row = await session.scalar(select(ConversationModel).where(*scope(ConversationModel, tenant, novel), ConversationModel.id == UUID(conversation_id)).with_for_update())
            if row is None:
                raise LookupError("对话不存在")
            row.title, row.updated_at = title, utc_now()
            return payload(row)

    async def assets(self, tenant, novel):
        async with self.async_session() as session:
            rows = (await session.scalars(select(AssetModel).where(*scope(AssetModel, tenant, novel)).order_by(AssetModel.updated_at.desc()))).all()
            return [payload(row) for row in rows]

    async def basis(self, tenant, novel):
        async with self.async_session() as session, session.begin():
            row = await _lock_novel(session, UUID(tenant), UUID(novel))
            if row is None:
                raise LookupError("作品不存在")
            return await basis_in_session(session, tenant, novel, row)

    async def asset(self, tenant, novel, asset_id):
        async with self.async_session() as session:
            row = await session.scalar(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.id == UUID(asset_id)))
            return payload(row) if row is not None else None

    async def save_asset(self, tenant, novel, command, provenance=None):
        async with self.async_session() as session, session.begin():
            if await _lock_novel(session, UUID(tenant), UUID(novel)) is None:
                raise LookupError("作品不存在")
            origin = await message_provenance(session, tenant, novel, command.source_message_id, provenance or {})
            now = utc_now()
            row = AssetModel(id=uuid4(), tenant_id=UUID(tenant), novel_id=UUID(novel), title=command.title, kind=command.kind,
                             content=command.content, version=1, source_message_id=command.source_message_id,
                             provenance=origin, created_at=now, updated_at=now)
            session.add(row)
            await session.flush()
            add_version(session, row)
            await index_source(session, tenant, novel, "asset", row.id, row.title, row.version, row.content, row.kind)
            return payload(row)

    async def edit_asset(self, tenant, novel, asset_id, command):
        async with self.async_session() as session, session.begin():
            await _lock_novel(session, UUID(tenant), UUID(novel))
            row = await session.scalar(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.id == UUID(asset_id)).with_for_update())
            if row is None:
                raise LookupError("资产不存在")
            if row.version != command.expected_version:
                raise WorkbenchConflict("资产已更新，请重新载入")
            row.title, row.kind, row.content = command.title, command.kind, command.content
            row.version += 1
            row.review = None
            row.updated_at = utc_now()
            add_version(session, row)
            await index_source(session, tenant, novel, "asset", row.id, row.title, row.version, row.content, row.kind)
            return payload(row)

    async def asset_versions(self, tenant, novel, asset_id):
        async with self.async_session() as session:
            rows = (await session.scalars(select(AssetVersionModel).where(*scope(AssetVersionModel, tenant, novel), AssetVersionModel.asset_id == UUID(asset_id)).order_by(AssetVersionModel.version.desc()))).all()
            return [payload(row) for row in rows]

    async def create_job(self, tenant, novel, conversation_id, command, key, snapshot):
        command_data = {"conversation_id": conversation_id, **command.model_dump(mode="json")}
        command_digest = digest(command_data)
        async with self.async_session() as session, session.begin():
            novel_row = await _lock_novel(session, UUID(tenant), UUID(novel))
            if novel_row is None:
                raise LookupError("作品不存在")
            old = await session.scalar(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.command_key == key))
            if old:
                if old.command_digest != command_digest:
                    raise WorkbenchConflict("同一请求标识已用于不同内容")
                return job_payload(old), False
            await assert_snapshot_current(session, tenant, novel, novel_row, snapshot)
            conversation = await session.scalar(select(ConversationModel).where(*scope(ConversationModel, tenant, novel), ConversationModel.id == UUID(conversation_id)))
            if conversation is None:
                raise LookupError("对话不存在")
            job_id, message_id = uuid4(), uuid4()
            now = await next_message_time(session, tenant, novel, conversation.id)
            user = MessageModel(id=uuid4(), tenant_id=UUID(tenant), novel_id=UUID(novel), conversation_id=conversation.id,
                                role="user", content=command.text, status="completed", intent=command.intent, sources=[], created_at=now)
            assistant = MessageModel(id=message_id, tenant_id=UUID(tenant), novel_id=UUID(novel), conversation_id=conversation.id,
                                     role="assistant", content="", status="queued", intent=command.intent, job_id=job_id, sources=[], created_at=now + timedelta(microseconds=1))
            row = JobModel(id=job_id, tenant_id=UUID(tenant), novel_id=UUID(novel), conversation_id=conversation.id, message_id=message_id,
                           command_key=key, command_digest=command_digest, request=command.model_dump(mode="json"), snapshot=snapshot,
                           status="queued", content="", sources=[], intent=command.intent, chapter_index=snapshot.get("chapter_index", command.chapter_index),
                           target_chapter_id=command.target_chapter_id, created_at=now, updated_at=now)
            session.add_all([user, assistant, row])
            conversation.updated_at = now
            await session.flush()
            return job_payload(row), True

    async def job(self, tenant, novel, job_id, private=False):
        async with self.async_session() as session:
            row = await session.scalar(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.id == UUID(job_id)))
            return job_payload(row, private) if row else None

    async def update_job(self, tenant, novel, job_id, **fields):
        async with self.async_session() as session, session.begin():
            row = await session.scalar(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.id == UUID(job_id)).with_for_update())
            if row is None:
                raise LookupError("任务不存在")
            for name, value in fields.items():
                setattr(row, name, value)
            row.updated_at = utc_now()
            message = await session.scalar(select(MessageModel).where(*scope(MessageModel, tenant, novel), MessageModel.id == row.message_id))
            if message:
                message.content, message.status, message.sources = row.content, row.status, row.sources
            return job_payload(row)

    async def retry_job(self, tenant, novel, job_id):
        async with self.async_session() as session, session.begin():
            novel_row = await _lock_novel(session, UUID(tenant), UUID(novel))
            if novel_row is None:
                raise LookupError("作品不存在")
            row = await session.scalar(select(JobModel).where(*scope(JobModel, tenant, novel), JobModel.id == UUID(job_id)).with_for_update())
            if row is None:
                raise LookupError("任务不存在")
            if row.status not in ("failed", "stopped"):
                return job_payload(row), False
            await assert_snapshot_current(session, tenant, novel, novel_row, row.snapshot)
            attempts = [*row.snapshot.get("previous_attempts", []), {"content": row.content, "status": row.status}][-5:]
            row.snapshot = {**row.snapshot, "previous_attempts": attempts}
            row.status, row.error, row.updated_at = "queued", None, utc_now()
            message = await session.scalar(select(MessageModel).where(*scope(MessageModel, tenant, novel), MessageModel.id == row.message_id))
            if message:
                message.status = "queued"
            return job_payload(row), True

    async def search(self, tenant, novel, query, before_chapter=None):
        terms = query_terms(query)
        if not terms:
            return []
        async with self.async_session() as session:
            has_trgm = await session.scalar(text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_trgm')"))
            similarity = func.similarity(SourceChunkModel.text, query) if has_trgm else None
            stmt = select(SourceChunkModel)
            if similarity is not None:
                stmt = stmt.add_columns(similarity.label("similarity"))
            conditions = [or_(SourceChunkModel.text.icontains(term, autoescape=True), SourceChunkModel.title.icontains(term, autoescape=True)) for term in terms]
            official = select(ChapterModel.id).where(
                *scope(ChapterModel, tenant, novel), ChapterModel.id == SourceChunkModel.source_id,
                ChapterModel.version == SourceChunkModel.version, ChapterModel.status.in_(("completed", "revised")),
            ).exists()
            active_asset = select(AssetModel.id).where(
                *scope(AssetModel, tenant, novel), AssetModel.id == SourceChunkModel.source_id,
                AssetModel.version == SourceChunkModel.version, AssetModel.kind.in_(ACTIVE_KINDS),
            ).exists()
            stmt = stmt.where(
                *scope(SourceChunkModel, tenant, novel),
                or_((SourceChunkModel.source_type == "chapter") & official,
                    (SourceChunkModel.source_type == "asset") & active_asset),
                or_(*conditions),
            )
            if before_chapter is not None:
                stmt = stmt.where(or_(SourceChunkModel.chapter_index.is_(None), SourceChunkModel.chapter_index < before_chapter))
            if similarity is not None:
                stmt = stmt.order_by(similarity.desc())
            rows = (await session.execute(stmt.limit(240))).all()
            candidates = []
            for row in rows:
                item = payload(row[0])
                if similarity is not None:
                    item["similarity"] = row[1]
                candidates.append(item)
            return rank_sources(query, candidates)

    async def ensure_index(self, tenant, novel):
        """Backfill legacy sources without rewriting an already current index."""
        missing = False
        async with self.async_session() as session:
            for model, source_type in ((AssetModel, "asset"), (ChapterModel, "chapter")):
                indexed = select(SourceChunkModel.id).where(
                    *scope(SourceChunkModel, tenant, novel), SourceChunkModel.source_type == source_type,
                    SourceChunkModel.source_id == model.id, SourceChunkModel.version == model.version,
                ).exists()
                stmt = select(model.id).where(
                    *scope(model, tenant, novel), func.length(func.btrim(model.content, " \t\r\n")) > 0, ~indexed,
                )
                if source_type == "chapter":
                    stmt = stmt.where(model.status.in_(("completed", "revised")))
                if await session.scalar(stmt.limit(1)) is not None:
                    missing = True
                    break
        if missing:
            await self.reindex(tenant, novel)
        return missing

    async def reindex(self, tenant, novel):
        async with self.async_session() as session, session.begin():
            novel_row = await _lock_novel(session, UUID(tenant), UUID(novel))
            if novel_row is None:
                raise LookupError("作品不存在")
            await session.execute(delete(SourceChunkModel).where(*scope(SourceChunkModel, tenant, novel)))
            assets = (await session.scalars(select(AssetModel).where(*scope(AssetModel, tenant, novel)))).all()
            chapters = (await session.scalars(select(ChapterModel).where(*scope(ChapterModel, tenant, novel), ChapterModel.status.in_(("completed", "revised"))))).all()
            for row in assets:
                await index_source(session, tenant, novel, "asset", row.id, row.title, row.version, row.content, row.kind)
            for row in chapters:
                await index_source(session, tenant, novel, "chapter", row.id, row.title, row.version, row.content, "chapter", row.chapter_index)
            return {"assets": len(assets), "chapters": len(chapters)}

    async def recover_interrupted(self):
        async with self.async_session() as session, session.begin():
            rows = (await session.scalars(select(JobModel).where(JobModel.status.in_(("running", "queued"))))).all()
            for row in rows:
                row.status, row.error = "failed", "服务重启，已生成内容保留，可重试"
                message = await session.get(MessageModel, row.message_id)
                if message:
                    message.status, message.content = "failed", row.content

    async def set_review(self, tenant, novel, asset_id, version, review):
        async with self.async_session() as session, session.begin():
            row = await session.scalar(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.id == UUID(asset_id)).with_for_update())
            if row is None:
                raise LookupError("资产不存在")
            if row.version != version:
                raise WorkbenchConflict("资产已修改，审读结果失效")
            row.review = review
            return payload(row)

    async def adopt(self, tenant, novel, asset_id, command, prepared):
        """Commit chapter, memory, source index and adoption receipt under one lock."""
        from service.entities.chapter import Chapter
        async with self.async_session() as session, session.begin():
            novel_row = await _lock_novel(session, UUID(tenant), UUID(novel))
            if novel_row is None:
                raise LookupError("作品不存在")
            asset = await session.scalar(select(AssetModel).where(*scope(AssetModel, tenant, novel), AssetModel.id == UUID(asset_id)).with_for_update())
            if asset is None:
                raise LookupError("资产不存在")
            if asset.kind != "chapter":
                raise WorkbenchConflict("只有章节草稿可以采纳为正式章节")
            if asset.version != command.expected_version:
                raise WorkbenchConflict("草稿版本已变化，请重新载入")
            existing_receipt = asset.provenance.get("adoption")
            if existing_receipt and existing_receipt["asset_version"] == asset.version:
                return existing_receipt
            if prepared["basis"] != await basis_in_session(session, tenant, novel, novel_row):
                raise WorkbenchConflict("作品或有效设定已变化，请重新生成或审读")
            review = asset.review or {}
            validate_adoption_review(review, asset.version, command, prepared["basis"])
            target, index, chapters = await adoption_position(session, tenant, novel, command)
            status = {"reviewed": "passed", "with_issues": "accepted_with_issues", "unreviewed": "accepted_unreviewed"}[command.acceptance]
            decision = {"review_status": status, "quality_score": review.get("gate", {}).get("score"),
                        "workbench_asset_id": asset_id, "asset_version": asset.version}
            chapter_id = target.id if target else uuid4()
            version = target.version + 1 if target else 1
            chapter = Chapter(
                id=chapter_id, novel_id=UUID(novel), chapter_index=index, title=asset.title,
                content=asset.content, word_count=len(asset.content), version=version, status="completed",
                user_decision=decision, reflection_issues=review.get("issues", []),
            )
            if target:
                await replace_adopted_chapter(session, tenant, novel, novel_row, target, chapter, chapters, prepared)
            else:
                await append_adopted_chapter(session, tenant, novel, novel_row, chapter, chapters, prepared)
            await index_source(session, tenant, novel, "chapter", chapter_id, asset.title, version, asset.content, "chapter", index)
            receipt = {"chapter_id": str(chapter_id), "chapter_index": index, "chapter_version": version, "asset_version": asset.version, "review_status": status}
            asset.adopted_chapter_id = chapter_id
            asset.provenance = {**asset.provenance, "adoption": receipt}
            return receipt
