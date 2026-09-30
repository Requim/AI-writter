"""创作会话仓储：小说行锁、租约校验、CAS、幂等与预算预记账。"""

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select

from application.creative.errors import CreativeConflict, CreativePause
from application.creative.evidence import content_hash, verify_evidence
from application.execution_fence import execution_fence
from config import settings
from infrastructure.database.creative_models import AuthorRecordModel, CreativeRecordModel, CreativeRequestModel, CreativeSessionModel
from infrastructure.database.models import ChapterModel, NovelModel, TenantModel
from infrastructure.database.runtime_guard import assert_execution_owner
from infrastructure.database.runtime_models import WorkflowArtifactModel, WorkflowLeaseModel
from service.value_objects.creative import AuthorConfiguration, CreativeRecord


def _scope(model: Any, tenant: UUID, novel: UUID):
    return select(model).where(model.tenant_id == tenant, model.novel_id == novel)


def _digest(value: Any) -> str:
    return content_hash(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def row_dict(row: Any) -> dict[str, Any]:
    return {
        column.name: (str(value) if isinstance(value, UUID) else value.isoformat() if isinstance(value, datetime) else value)
        for column in row.__table__.columns
        if (value := getattr(row, column.name)) is not None
    }


async def lock_creative_novel(session: Any, tenant: UUID, novel: UUID) -> NovelModel:
    row = await session.scalar(select(NovelModel).where(
        NovelModel.tenant_id == tenant, NovelModel.id == novel,
    ).with_for_update())
    if row is None:
        raise LookupError("小说不存在")
    await assert_execution_owner(session, tenant, novel)
    if execution_fence.get() is None:
        active = await session.scalar(_scope(WorkflowLeaseModel, tenant, novel).where(
            WorkflowLeaseModel.expires_at > func.clock_timestamp(),
        ))
        if active:
            raise CreativeConflict("作品正在执行，请在章边界暂停后修改")
    return row


async def create_creative_session(
    session: Any, tenant: UUID, novel: UUID, raw: dict[str, Any], chapters: int,
) -> CreativeSessionModel:
    """与新书创建共用事务；调用方不得为旧书补建自主模式会话。"""
    config = AuthorConfiguration.model_validate(raw)
    tenant_row = await session.get(TenantModel, tenant)
    if not settings.AUTONOMOUS_AUTHOR_ENABLED or not tenant_row.autonomous_author_enabled:
        raise CreativePause("feature_disabled", "自主作家模式尚未对该租户开放")
    if not settings.NOVEL_PLANNING_V1_ENABLED or not tenant_row.novel_planning_v1_enabled:
        raise CreativePause("planning_disabled", "自主作家模式需要先启用整书规划")
    if not 1 <= chapters <= 200:
        raise ValueError("自主作家模式必须明确1-200章的规模")
    config = await default_profile_binding(session, tenant, novel, config)
    await validate_profile_binding(session, tenant, config)
    row = CreativeSessionModel(
        tenant_id=tenant, novel_id=novel, config=config.model_dump(mode="json"),
        limits=config.budget.resolved(chapters, tenant_row.autonomous_request_limit),
    )
    session.add(row)
    return row


async def default_profile_binding(session, tenant, novel, config):
    """未显式选档案的新书使用最新适用跨书档案；当前书的绑定不随之变化。"""
    if config.author_profile_id is not None:
        return config
    novel_row = await session.get(NovelModel, novel)
    rows = await session.scalars(select(AuthorRecordModel).where(
        AuthorRecordModel.tenant_id == tenant, AuthorRecordModel.kind == "profile",
    ).order_by(AuthorRecordModel.created_at.desc(), AuthorRecordModel.version.desc()))
    seen = set()
    for row in rows:
        if row.key in seen:
            continue
        seen.add(row.key)
        preferences = row.payload.get("preferences", [])
        applicable = any(p.get("scope") == "global" or (
            p.get("scope") == "genre" and p.get("genre") == novel_row.novel_type
        ) for p in preferences)
        if applicable:
            return config.model_copy(update={"author_profile_id": row.key, "author_profile_version": row.version})
    return config


async def validate_profile_binding(session, tenant, config):
    if config.author_profile_id is None:
        return
    profile = await session.scalar(select(AuthorRecordModel).where(
        AuthorRecordModel.tenant_id == tenant, AuthorRecordModel.kind == "profile",
        AuthorRecordModel.key == config.author_profile_id,
        AuthorRecordModel.version == config.author_profile_version,
    ))
    if profile is None:
        raise ValueError("作者档案版本不存在或不属于当前租户")


class PostgresCreativeRepository:
    def __init__(self, session_factory: Any):
        self.sessions = session_factory

    async def get_session(self, tenant_id: str, novel_id: str) -> dict[str, Any] | None:
        """按租户读取稳定创作会话，不从请求或checkpoint信任预算。"""
        async with self.sessions() as session:
            row = await session.scalar(_scope(CreativeSessionModel, UUID(tenant_id), UUID(novel_id)))
            return row_dict(row) if row else None

    async def require_enabled(self, tenant_id: str) -> None:
        async with self.sessions() as session:
            await _check_feature(session, UUID(tenant_id))

    async def records(self, tenant_id: str, novel_id: str, kind: str | None = None) -> list[dict]:
        async with self.sessions() as session:
            statement = _scope(CreativeRecordModel, UUID(tenant_id), UUID(novel_id))
            if kind:
                statement = statement.where(CreativeRecordModel.kind == kind)
            rows = (await session.scalars(statement.order_by(CreativeRecordModel.created_at, CreativeRecordModel.version))).all()
            return [row_dict(row) for row in rows]

    async def latest(self, tenant_id: str, novel_id: str, kind: str, key: str) -> dict | None:
        async with self.sessions() as session:
            statement = _scope(CreativeRecordModel, UUID(tenant_id), UUID(novel_id)).where(
                CreativeRecordModel.kind == kind, CreativeRecordModel.key == key,
            ).order_by(CreativeRecordModel.version.desc()).limit(1)
            row = await session.scalar(statement)
            return row_dict(row) if row else None

    async def command(self, tenant_id, novel_id, idempotency_key):
        """返回小说范围内的历史命令，不因后续操作丢失重放依据。"""
        async with self.sessions() as session:
            row = await session.scalar(_scope(CreativeRecordModel, UUID(tenant_id), UUID(novel_id)).where(
                CreativeRecordModel.idempotency_key == idempotency_key,
            ))
            return row_dict(row) if row else None

    async def put(
        self, tenant_id: str, novel_id: str, record: CreativeRecord,
        *, expected_version: int, idempotency_key: str,
    ) -> dict:
        """追加不可变产物，幂等重放不重复生成，陈旧版本不可覆盖。"""
        if not idempotency_key or len(idempotency_key) > 128:
            raise ValueError("必须提供不超过128字符的幂等键")
        tenant, novel = UUID(tenant_id), UUID(novel_id)
        digest = _digest(record.model_dump(mode="json"))
        async with self.sessions.begin() as session:
            await lock_creative_novel(session, tenant, novel)
            base = _scope(CreativeRecordModel, tenant, novel)
            prior = await session.scalar(base.where(CreativeRecordModel.idempotency_key == idempotency_key))
            if prior:
                if prior.digest != digest:
                    raise CreativeConflict("同一幂等键对应不同创作产物")
                return row_dict(prior)
            current = await session.scalar(base.where(
                CreativeRecordModel.kind == record.kind, CreativeRecordModel.key == record.key,
            ).order_by(CreativeRecordModel.version.desc()).limit(1))
            if (current.version if current else 0) != expected_version:
                raise CreativeConflict("创作产物版本已更新")
            await _validate_record_scope(session, tenant, novel, record)
            await self._verify_record_evidence(session, tenant, novel, record)
            row = CreativeRecordModel(
                tenant_id=tenant, novel_id=novel, version=expected_version + 1,
                idempotency_key=idempotency_key, digest=digest,
                **record.model_dump(mode="json"),
            )
            row.run_artifact_id = await _runtime_artifact(session, tenant, novel, record, digest)
            session.add(row)
            await session.flush()
            return row_dict(row)

    async def _verify_record_evidence(self, session, tenant, novel, record):
        for evidence in record.evidence:
            chapter = await session.scalar(_scope(ChapterModel, tenant, novel).where(ChapterModel.id == evidence.chapter_id))
            if chapter is None:
                raise ValueError("证据章节不属于当前租户和作品")
            verify_evidence(evidence, row_dict(chapter))

    async def reserve(self, tenant_id: str, novel_id: str, bucket: str, stage: str) -> str:
        """物理请求发送前原子记账；超时或结果未知不退款。"""
        tenant, novel = UUID(tenant_id), UUID(novel_id)
        async with self.sessions.begin() as session:
            await lock_creative_novel(session, tenant, novel)
            row = await session.scalar(_scope(CreativeSessionModel, tenant, novel).with_for_update())
            if row is None:
                raise CreativePause("session_missing", "缺少持久化创作会话")
            await _check_feature(session, tenant)
            counters = increment_budget(row.limits, row.counters, bucket)
            row.counters = counters
            request = CreativeRequestModel(tenant_id=tenant, novel_id=novel, session_id=row.id, bucket=bucket, stage=stage)
            session.add(request)
            await session.flush()
            return str(request.id)

    async def finish_request(self, tenant_id: str, novel_id: str, request_id: str, usage: dict) -> None:
        async with self.sessions.begin() as session:
            tenant, novel = UUID(tenant_id), UUID(novel_id)
            await lock_creative_novel(session, tenant, novel)
            row = await session.scalar(_scope(CreativeRequestModel, tenant, novel).where(CreativeRequestModel.id == UUID(request_id)))
            if row is None:
                raise LookupError("模型请求不存在")
            row.status, row.usage = "completed", usage
            row.finished_at = datetime.now(timezone.utc)

    async def advance(self, tenant_id: str, novel_id: str, stage: str, status: str = "running") -> dict:
        async with self.sessions.begin() as session:
            tenant, novel = UUID(tenant_id), UUID(novel_id)
            await lock_creative_novel(session, tenant, novel)
            row = await session.scalar(_scope(CreativeSessionModel, tenant, novel).with_for_update())
            if row is None:
                raise LookupError("创作会话不存在")
            row.stage, row.status = stage, status
            row.version += 1
            await session.flush()
            return row_dict(row)

    async def chapters(self, tenant_id: str, novel_id: str, through: int | None = None) -> list[dict]:
        async with self.sessions() as session:
            query = _scope(ChapterModel, UUID(tenant_id), UUID(novel_id)).where(ChapterModel.status == "completed")
            if through is not None:
                query = query.where(ChapterModel.chapter_index < through)
            return [row_dict(row) for row in (await session.scalars(query.order_by(ChapterModel.chapter_index))).all()]

    async def canonical_life_status(self, tenant_id, novel_id, entity_id, chapter):
        """只读既有规范事实，传闻和正文抽取不得自行确认生死。"""
        from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
        snapshot = await PostgresStoryFactRepository(self.sessions).capture_constraints(tenant_id, novel_id, chapter)
        matches = [fact for fact in snapshot.fact_heads if str(fact.subject_id) == entity_id
                   and fact.predicate == "life_status" and fact.status == "confirmed"
                   and fact.valid_from_chapter <= chapter and (fact.valid_to_chapter is None or fact.valid_to_chapter >= chapter)]
        return matches[-1].value_text if matches else None


async def _check_feature(session, tenant_id):
    tenant = await session.get(TenantModel, tenant_id)
    if not settings.AUTONOMOUS_AUTHOR_ENABLED or not tenant or not tenant.autonomous_author_enabled:
        raise CreativePause("feature_disabled", "自主作家模式已关闭，创作现场保留")
    if not settings.NOVEL_PLANNING_V1_ENABLED or not tenant.novel_planning_v1_enabled:
        raise CreativePause("planning_disabled", "整书规划已关闭，自主模式安全暂停")


async def _validate_record_scope(session, tenant, novel, record):
    if record.kind != "source":
        return
    rows = (await session.scalars(_scope(CreativeRecordModel, tenant, novel).where(CreativeRecordModel.kind == "source"))).all()
    latest = {row.key: row for row in rows}
    if record.key in latest:
        raise ValueError("原始资料不可覆盖，请追加有来源的新资料")
    count = sum(len(row.payload.get("results", [row.payload])) for row in latest.values())
    incoming = len(record.payload.get("results", [record.payload]))
    if count + incoming > 20:
        raise ValueError("每书最多20份资料，包括检索获得的原始来源")


def increment_budget(limits: dict, counters: dict, bucket: str) -> dict:
    updated = dict(counters)
    root = bucket.split(":")[0]
    if root not in {"preparation", "chapter", "review", "search", "preparation_search"}:
        raise ValueError("未知预算池")
    if root == "chapter" and (":" not in bucket or not bucket.split(":")[1].isdigit()):
        raise ValueError("章节预算必须绑定章节号")
    if root == "chapter":
        chapter = int(bucket.split(":")[1])
        if bucket != f"chapter:{chapter}" or not 1 <= chapter <= limits["chapters"]:
            raise ValueError("章节预算超出约定规模或使用了非规范编号")
    elif bucket != root:
        raise ValueError("不能通过预算池别名绕过上限")
    charges = [bucket, "search"] if root == "preparation_search" else [bucket]
    for name in charges:
        limit = limits[name.split(":")[0]]
        if updated.get(name, 0) >= limit:
            raise CreativePause("budget_exhausted", f"{name} 调用预算已耗尽")
        updated[name] = updated.get(name, 0) + 1
    return updated


async def _runtime_artifact(session, tenant, novel, record, digest):
    owner = execution_fence.get()
    if owner is None:
        return None
    artifact = WorkflowArtifactModel(
        id=uuid4(), tenant_id=tenant, novel_id=novel, run_id=owner.run_id,
        kind="creative", digest=digest, payload=record.model_dump(mode="json"),
    )
    session.add(artifact)
    await session.flush()
    return artifact.id
