"""小说创作资源与租户作者档案API，长任务仍由原工作流执行。"""

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import get_tenant_context
from application.creative.errors import CreativeConflict, CreativePause
from application.creative.feedback import feedback_hypotheses
from config import settings
from infrastructure.database.author_repository import PostgresAuthorRepository
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.creative_commands import record_control, replay_control
from infrastructure.database.creative_repository import PostgresCreativeRepository, lock_creative_novel, row_dict
from infrastructure.database.creative_repository import _digest
from infrastructure.database.models import NovelModel, TenantModel
from service.entities.identity import TenantContext
from service.value_objects.author_style import AuthorProfile, AuthorSample
from service.value_objects.creative import BudgetLimits, CreativeRecord, RecordKind, ResearchSource
from service.value_objects.reader_feedback import ReaderFeedback

router = APIRouter()
author_router = APIRouter()


def creative_repository(request: Request):
    return PostgresCreativeRepository(request.app.state.repository.async_session)


def author_repository(request: Request):
    return PostgresAuthorRepository(request.app.state.repository.async_session)


async def _session(repo, context, novel_id):
    found = await repo.get_session(str(context.tenant_id), str(novel_id))
    if not found:
        raise HTTPException(404, "自主创作会话不存在")
    return found


def _key(value):
    if not value or len(value) > 128:
        raise HTTPException(422, "必须提供不超过128字符的Idempotency-Key")
    return value


async def _request_replay(repo, context, novel_id, key, command):
    saved = await repo.command(str(context.tenant_id), str(novel_id), _key(key))
    if saved and saved["input_versions"].get("request_digest") != _digest(command):
        raise HTTPException(409, "同一幂等键对应不同请求")
    return saved


async def _save(repo, context, novel_id, record, key, expected=0):
    await _session(repo, context, novel_id)
    try:
        return await repo.put(str(context.tenant_id), str(novel_id), record,
                              expected_version=expected, idempotency_key=_key(key))
    except CreativeConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, LookupError) as error:
        raise HTTPException(422, str(error)) from error


@router.get("/{novel_id}/creative")
async def overview(novel_id: UUID, context: TenantContext = Depends(get_tenant_context), repo=Depends(creative_repository)):
    """返回真实阶段、持久化预算和分项状态，不将模型结果标为真人验证。"""
    session = await _session(repo, context, novel_id)
    records = await repo.records(str(context.tenant_id), str(novel_id))
    counts = {kind: sum(r["kind"] == kind for r in records) for kind in {r["kind"] for r in records}}
    return {"session": session, "artifact_counts": counts, "real_reader_validation": "not_performed"}


@router.get("/{novel_id}/creative/artifacts")
async def artifacts(novel_id: UUID, kind: RecordKind | None = None, context: TenantContext = Depends(get_tenant_context), repo=Depends(creative_repository)):
    await _session(repo, context, novel_id)
    return await repo.records(str(context.tenant_id), str(novel_id), kind)


@router.get("/{novel_id}/creative/{resource}")
async def resources(novel_id: UUID, resource: Literal["characters", "relationships", "foreshadow", "reader-state", "sources", "feedback", "experiments", "budget"],
                    context: TenantContext = Depends(get_tenant_context), repo=Depends(creative_repository)):
    session = await _session(repo, context, novel_id)
    if resource == "budget":
        return {key: session[key] for key in ("id", "version", "limits", "counters")}
    kind = {"characters": "character", "relationships": "relationship", "foreshadow": "foreshadow",
            "reader-state": "reader_state", "sources": "source", "feedback": "feedback", "experiments": "experiment"}[resource]
    return await repo.records(str(context.tenant_id), str(novel_id), kind)


@router.post("/{novel_id}/creative/sources", status_code=201)
async def add_source(novel_id: UUID, payload: ResearchSource, context: TenantContext = Depends(get_tenant_context),
                     key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    if payload.origin == "tavily":
        raise HTTPException(422, "用户上传资料不能冒充检索服务来源")
    return await _save(repo, context, novel_id, CreativeRecord(
        kind="source", key=_digest(_key(key)), payload=payload.model_dump(mode="json"), source="author", status="available",
    ), key)


@router.post("/{novel_id}/creative/feedback", status_code=201)
async def add_feedback(novel_id: UUID, payload: ReaderFeedback, context: TenantContext = Depends(get_tenant_context),
                       key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    if payload.source == "author_instruction" and not context.can_manage_members():
        raise HTTPException(403, "只有作者管理员可以提交明确作者指令")
    chapters = {c["id"]: c for c in await repo.chapters(str(context.tenant_id), str(novel_id))}
    if any(str(e.chapter_id) not in chapters for e in payload.evidence):
        raise HTTPException(422, "反馈引用的章节不属于当前作品")
    if any(e.chapter_version > chapters[str(e.chapter_id)]["version"] for e in payload.evidence):
        raise HTTPException(422, "反馈不能引用尚不存在的未来章节版本")
    stale = any(chapters[str(e.chapter_id)]["version"] != e.chapter_version for e in payload.evidence)
    record = CreativeRecord(kind="feedback", key=_digest(_key(key)), payload=payload.model_dump(mode="json"),
                            source="human_reader" if payload.source == "human_reader" else "author" if payload.source == "author_instruction" else "model",
                            evidence=[] if stale else payload.evidence, status="stale_unverified" if stale else "received")
    saved = await _save(repo, context, novel_id, record, key)
    feedback = [ReaderFeedback.model_validate(r["payload"]) for r in await repo.records(str(context.tenant_id), str(novel_id), "feedback") if r["status"] != "stale_unverified"]
    return {"record": saved, "hypotheses": feedback_hypotheses(feedback)}


class VersionedSample(BaseModel):
    sample_id: UUID | None = None
    sample: AuthorSample


class VersionedProfile(BaseModel):
    profile_id: UUID | None = None
    expected_version: int = Field(default=0, ge=0)
    profile: AuthorProfile


@author_router.get("/{kind}")
async def author_records(kind: Literal["samples", "profiles"], context: TenantContext = Depends(get_tenant_context), repo=Depends(author_repository)):
    return await repo.records(str(context.tenant_id), "sample" if kind == "samples" else "profile")


async def _author_save(repo, context, kind, resource_id, payload, expected, key):
    if not context.can_manage_members():
        raise HTTPException(403, "仅租户作者管理员可修改跨书作者档案")
    resource_id = resource_id or uuid5(context.tenant_id, f"{kind}:{_key(key)}")
    try:
        return await repo.put(str(context.tenant_id), kind, str(resource_id), payload, expected, _key(key))
    except CreativeConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, LookupError) as error:
        raise HTTPException(422, str(error)) from error


@author_router.post("/samples", status_code=201)
async def add_sample(payload: VersionedSample, context: TenantContext = Depends(get_tenant_context),
                     key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(author_repository)):
    return await _author_save(repo, context, "sample", payload.sample_id, payload.sample.model_dump(mode="json"), 0, key)


@author_router.post("/profiles", status_code=201)
async def add_profile(payload: VersionedProfile, context: TenantContext = Depends(get_tenant_context),
                      key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(author_repository)):
    return await _author_save(repo, context, "profile", payload.profile_id, payload.profile.model_dump(mode="json"), payload.expected_version, key)


class BudgetUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    limits: BudgetLimits


@router.put("/{novel_id}/creative/budget")
async def update_budget(novel_id: UUID, payload: BudgetUpdate, context: TenantContext = Depends(get_tenant_context),
                        key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    _key(key)
    try:
        return await _update_budget(repo, context, novel_id, payload, key)
    except CreativeConflict as error:
        raise HTTPException(409, str(error)) from error
    except (ValueError, LookupError) as error:
        raise HTTPException(422, str(error)) from error


async def _update_budget(repo, context, novel_id, payload, key):
    async with repo.sessions.begin() as session:
        novel = await lock_creative_novel(session, context.tenant_id, novel_id)
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id, CreativeSessionModel.novel_id == novel_id,
        ).with_for_update())
        if row is None:
            raise LookupError("自主会话不存在")
        command = {"operation": "budget", **payload.model_dump(mode="json")}
        previous = await replay_control(session, context.tenant_id, novel_id, key, command)
        if previous is not None:
            return previous
        if row.version != payload.expected_version:
            raise CreativeConflict("预算版本已更新")
        tenant = await session.get(TenantModel, context.tenant_id)
        limits = payload.limits.resolved(novel.total_outline["total_chapters"], tenant.autonomous_request_limit)
        if any(count > limits[bucket.split(":")[0]] for bucket, count in row.counters.items()):
            raise ValueError("新预算不得低于已发生消耗")
        row.limits, row.version = limits, row.version + 1
        row.config = {**row.config, "budget": payload.limits.model_dump(mode="json")}
        await session.flush()
        result = row_dict(row)
        record_control(session, context.tenant_id, novel_id, key, command, result)
        return result
