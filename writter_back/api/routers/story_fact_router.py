"""作者事实台账、历史与两步纠错接口，全部按当前租户授权。"""
from uuid import UUID
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from api.dependencies import get_tenant_context
from application.fact_corrections import FactCorrectionInput, make_proposal, sign_proposal, verify_proposal, validate_entity_kinds
from config import settings
from infrastructure.database.models import ChapterModel
from infrastructure.database.story_fact_repository import PostgresStoryFactRepository
from service.entities.identity import TenantContext
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.story_fact import Predicate, StoryEntity

router = APIRouter()


async def store_for(request: Request, novel_id: UUID, context: TenantContext) -> PostgresStoryFactRepository:
    repo = request.app.state.repository
    if await repo.find_by_id(str(context.tenant_id), str(novel_id)) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return PostgresStoryFactRepository(repo.async_session)


@router.get("/{novel_id}/facts")
async def ledger(novel_id: UUID, request: Request, context: TenantContext = Depends(get_tenant_context)) -> Any:
    """返回同一锁内读取的实体和事实版本头。"""
    store = await store_for(request, novel_id, context)
    return await store.capture_constraints(str(context.tenant_id), str(novel_id), 1)


@router.post("/{novel_id}/facts/entities", response_model=StoryEntity)
async def create_entity(novel_id: UUID, entity: StoryEntity, request: Request, context: TenantContext = Depends(get_tenant_context)) -> StoryEntity:
    """显式登记人物、家族、地点或物品，不从名字猜测关系。"""
    store = await store_for(request, novel_id, context)
    try:
        return await store.ensure_entity(str(context.tenant_id), str(novel_id), entity)
    except (ValueError, FactVersionConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{novel_id}/facts/history/{subject_id}/{predicate}")
async def history(novel_id: UUID, subject_id: UUID, predicate: Predicate, request: Request,
                  context: TenantContext = Depends(get_tenant_context)) -> Any:
    """查看原始证据及全部历史版本，包含撤回记录。"""
    store = await store_for(request, novel_id, context)
    return await store.list_history(str(context.tenant_id), str(novel_id), subject_id, predicate)


@router.post("/{novel_id}/facts/proposals")
async def preview(novel_id: UUID, change: FactCorrectionInput, request: Request,
                  context: TenantContext = Depends(get_tenant_context)) -> Any:
    """校验新事实并签发短期确认提案，此操作不修改台账。"""
    store = await store_for(request, novel_id, context)
    snapshot = await store.capture_constraints(str(context.tenant_id), str(novel_id), change.valid_from_chapter)
    previous = next((fact for fact in snapshot.fact_heads if (fact.subject_id, fact.predicate) == (change.subject_id, change.predicate)), None)
    if (previous.version if previous else 0) != change.expected_version:
        raise HTTPException(status_code=409, detail="事实版本已变化，请重新加载")
    ids = {entity.id for entity in snapshot.entities}
    if change.subject_id not in ids or (change.object_entity_id and change.object_entity_id not in ids):
        raise HTTPException(status_code=422, detail="事实主体或对象未登记")
    try:
        validate_entity_kinds(change, snapshot.entities)
        proposal = make_proposal(context, novel_id, change)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"proposal": proposal, "previous": previous, "token": sign_proposal(proposal, settings.JWT_SECRET)}


class Confirmation(BaseModel):
    token: str = Field(min_length=1, max_length=20000)


@router.post("/{novel_id}/facts/confirm")
async def confirm(novel_id: UUID, body: Confirmation, request: Request, context: TenantContext = Depends(get_tenant_context)) -> Any:
    """验证签名和当前版本，幂等追加版本而非覆盖；旧生成快照自动失效。"""
    store = await store_for(request, novel_id, context)
    try:
        proposal = verify_proposal(body.token, settings.JWT_SECRET, context, novel_id)
        return await store.append_fact(str(context.tenant_id), str(novel_id), proposal.fact,
            expected_version=proposal.expected_version, idempotency_key="correction:" + str(proposal.id))
    except FactVersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{novel_id}/facts/conflicts")
async def conflicts(novel_id: UUID, request: Request, context: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    """列出归档事实回执；无回执的历史章明确标为未验证。"""
    store = await store_for(request, novel_id, context)
    async with store.async_session() as session:
        rows = await session.execute(select(ChapterModel.id, ChapterModel.chapter_index, ChapterModel.title, ChapterModel.user_decision)
            .where(ChapterModel.tenant_id == context.tenant_id, ChapterModel.novel_id == novel_id).order_by(ChapterModel.chapter_index))
        return [{"chapter_id": str(row.id), "chapter_number": row.chapter_index + 1, "title": row.title,
            "report": (row.user_decision or {}).get("fact_gate"),
            "review": (row.user_decision or {}).get("fact_review"),
            "status": ((row.user_decision or {}).get("fact_gate") or {}).get("status", (row.user_decision or {}).get("fact_validation_status", "legacy_unverified"))}
            for row in rows]
