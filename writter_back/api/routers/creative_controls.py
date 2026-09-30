"""自主作家灰度配置、资料导入、档案绑定与真人配对评价。"""

from datetime import datetime, timezone
from uuid import UUID, uuid5

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import get_tenant_context
from api.routers.creative_router import _key, _save, _session, _request_replay, creative_repository, router
from application.creative.feedback import evaluate_experiment
from application.creative.errors import CreativeConflict
from config import settings
from infrastructure.database.author_repository import PostgresAuthorRepository
from infrastructure.database.creative_models import CreativeSessionModel
from infrastructure.database.creative_commands import record_control, replay_control
from infrastructure.database.creative_repository import lock_creative_novel, row_dict
from infrastructure.database.creative_repository import _digest
from infrastructure.database.models import TenantModel
from infrastructure.research.tavily import decode_source_file
from service.entities.identity import TenantContext
from service.value_objects.creative import CreativeRecord, ResearchSource
from service.value_objects.reader_feedback import BlindJudgment, FeedbackExperiment


@router.get("/creative-options")
async def creative_options(context: TenantContext = Depends(get_tenant_context), repo=Depends(creative_repository)):
    """全局和租户开关同时启用才允许新书进入自主模式。"""
    async with repo.sessions() as session:
        tenant = await session.get(TenantModel, context.tenant_id)
        enabled = bool(settings.AUTONOMOUS_AUTHOR_ENABLED and tenant.autonomous_author_enabled
                       and settings.NOVEL_PLANNING_V1_ENABLED and tenant.novel_planning_v1_enabled)
        return {"enabled": enabled, "tenant_enabled": tenant.autonomous_author_enabled,
                "global_enabled": settings.AUTONOMOUS_AUTHOR_ENABLED,
                "request_limit": tenant.autonomous_request_limit, "new_books_only": True}


class TenantCreativeSettings(BaseModel):
    enabled: bool
    request_limit: int = Field(default=10000, ge=1, le=10000)


@router.put("/creative-options")
async def set_creative_options(payload: TenantCreativeSettings, context: TenantContext = Depends(get_tenant_context), repo=Depends(creative_repository)):
    if not context.is_platform_admin:
        raise HTTPException(403, "仅平台管理员可调整租户灰度")
    async with repo.sessions.begin() as session:
        tenant = await session.scalar(select(TenantModel).where(TenantModel.id == context.tenant_id).with_for_update())
        tenant.autonomous_author_enabled = payload.enabled
        tenant.autonomous_request_limit = payload.request_limit
    return {"tenant_enabled": payload.enabled, "request_limit": payload.request_limit}


@router.post("/{novel_id}/creative/sources/file", status_code=201)
async def source_file(novel_id: UUID, filename: str, request: Request,
                      context: TenantContext = Depends(get_tenant_context),
                      key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    """流式限制请求体大小，仅接受UTF-8文本，不在文件系统保存用户路径。"""
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 200003:
            raise HTTPException(413, "资料超过大小限制")
    try:
        text = decode_source_file(filename, bytes(data))
    except (UnicodeError, ValueError) as error:
        raise HTTPException(422, str(error)) from error
    command = {"operation": "source_file", "filename": filename, "text": text}
    previous = await _request_replay(repo, context, novel_id, key, command)
    if previous:
        return previous
    source = ResearchSource(title=filename[:240], text=text, category="model_hypothesis", origin="user_file",
                            observed_at=datetime.now(timezone.utc), applicable_scope="用户资料，事实性质待分类核实")
    return await _save(repo, context, novel_id, CreativeRecord(
        kind="source", key=_digest(_key(key)), payload=source.model_dump(mode="json"), source="author", status="unclassified",
        input_versions={"request_digest": _digest(command)},
    ), key)


class ProfileBinding(BaseModel):
    expected_session_version: int = Field(ge=1)
    profile_id: UUID
    profile_version: int = Field(ge=1)
    apply_to_current_book: bool
    reason: str = Field(min_length=1, max_length=1000)


@router.put("/{novel_id}/creative/author-profile")
async def bind_profile(novel_id: UUID, payload: ProfileBinding, context: TenantContext = Depends(get_tenant_context),
                       key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    if not payload.apply_to_current_book:
        raise HTTPException(422, "必须明确要求在章边界应用当前书；新档案默认仅影响下一本书")
    if not context.can_manage_members():
        raise HTTPException(403, "仅作者管理员可切换档案")
    _key(key)
    authors = PostgresAuthorRepository(repo.sessions)
    try:
        await authors.profile(str(context.tenant_id), str(payload.profile_id), payload.profile_version)
        return await _bind_profile(repo, context, novel_id, payload, key)
    except CreativeConflict as error:
        raise HTTPException(409, str(error)) from error
    except LookupError as error:
        raise HTTPException(404, str(error)) from error


async def _bind_profile(repo, context, novel_id, payload, key):
    async with repo.sessions.begin() as session:
        novel = await lock_creative_novel(session, context.tenant_id, novel_id)
        row = await session.scalar(select(CreativeSessionModel).where(
            CreativeSessionModel.tenant_id == context.tenant_id, CreativeSessionModel.novel_id == novel_id,
        ).with_for_update())
        if row is None:
            raise LookupError("自主会话不存在")
        command = {"operation": "profile", **payload.model_dump(mode="json")}
        previous = await replay_control(session, context.tenant_id, novel_id, key, command)
        if previous is not None:
            return previous
        current = (novel.progress or {}).get("current_chapter", 0)
        if row.version != payload.expected_session_version or row.stage.startswith("postprocess:") or row.counters.get(f"chapter:{current + 1}", 0):
            raise CreativeConflict("会话版本已更新或尚未到达章边界")
        row.config = {**row.config, "author_profile_id": str(payload.profile_id),
                      "author_profile_version": payload.profile_version}
        row.version += 1
        await session.flush()
        result = {**row_dict(row), "applies_after_chapter": current}
        record_control(session, context.tenant_id, novel_id, key, command, result)
        return result


class HumanPairedFeedback(BaseModel):
    expected_version: int = Field(ge=1)
    reader_id: str = Field(min_length=1, max_length=120)
    order: str = Field(pattern="^(AB|BA)$")
    winner: str = Field(pattern="^(A|B|tie)$")
    reason: str = Field(min_length=1, max_length=2000)


@router.post("/{novel_id}/creative/experiments/{experiment_id}/human-review")
async def paired_review(novel_id: UUID, experiment_id: UUID, payload: HumanPairedFeedback,
                        context: TenantContext = Depends(get_tenant_context),
                        key: str | None = Header(None, alias="Idempotency-Key"), repo=Depends(creative_repository)):
    await _session(repo, context, novel_id)
    command = {"operation": "human_review", "experiment_id": str(experiment_id), **payload.model_dump(mode="json")}
    previous = await _request_replay(repo, context, novel_id, key, command)
    if previous:
        return previous
    records = await repo.records(str(context.tenant_id), str(novel_id), "experiment")
    record = next((r for r in records if r["id"] == str(experiment_id)), None)
    if not record:
        raise HTTPException(404, "实验不存在")
    latest = await repo.latest(str(context.tenant_id), str(novel_id), "experiment", record["key"])
    if record["version"] != payload.expected_version or latest["version"] != payload.expected_version:
        raise HTTPException(409, "实验版本已变化，请刷新后评价")
    experiment = FeedbackExperiment.model_validate(record["payload"])
    if any(j.source == "human" and j.evaluator_id == payload.reader_id for j in experiment.judgments):
        raise HTTPException(409, "同一读者的配对评价不可重复计票")
    judgment = BlindJudgment(evaluator_id=payload.reader_id, source="human", order=payload.order, winner=payload.winner, reason=payload.reason)
    updated = experiment.model_copy(update={"judgments": [*experiment.judgments, judgment]})
    completed = len(await repo.chapters(str(context.tenant_id), str(novel_id)))
    updated = evaluate_experiment(updated, completed)
    return await _save(repo, context, novel_id, CreativeRecord(
        kind="experiment", key=record["key"], payload=updated.model_dump(mode="json"),
        status=updated.status, source="human_reader", input_versions={**record["input_versions"], "request_digest": _digest(command)},
    ), key, expected=payload.expected_version)
