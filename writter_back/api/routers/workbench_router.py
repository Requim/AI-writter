"""Versioned author assets and persistent conversation generation endpoints."""

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.dependencies import get_tenant_context
from api.generation_policy import ensure_generation_enabled
from application.errors import WorkflowBusyError
from application.workbench.contracts import AdoptInput, AssetEdit, AssetInput, MessageInput, WorkbenchConflict
from application.workbench.service import legacy_sources
from config import settings
from infrastructure.database.workbench_repository import TERMINAL

router = APIRouter(prefix="/{novel_id}/workbench")


class ConversationInput(BaseModel):
    title: str = Field(default="新对话", min_length=1, max_length=240)


class VersionInput(BaseModel):
    expected_version: int = Field(ge=1)


class CopyInput(VersionInput):
    target_novel_id: UUID


async def get_workbench(request: Request, novel_id: UUID, context=Depends(get_tenant_context)):
    if await request.app.state.repository.find_by_id(str(context.tenant_id), str(novel_id)) is None:
        raise HTTPException(404, "作品不存在")
    return request.app.state.workbench_service


async def invoke(awaitable):
    try:
        return await awaitable
    except LookupError as error:
        raise HTTPException(404, str(error)) from error
    except (WorkbenchConflict, WorkflowBusyError) as error:
        raise HTTPException(409, {"code": "workbench_conflict", "message": str(error)}) from error


def allow_generation():
    if not settings.CONVERSATION_WORKBENCH_ENABLED:
        raise HTTPException(503, {"code": "workbench_disabled", "message": "对话创作暂未开放"})
    ensure_generation_enabled()


@router.get("/overview")
async def overview(novel_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    tenant, novel = str(context.tenant_id), str(novel_id)
    value = await service.novels.find_by_id_with_chapters(tenant, novel)
    await service.repository.ensure_index(tenant, novel)
    return {
        "novel": {"id": novel, "title": value.title, "novel_type": value.novel_type},
        "conversations": await service.repository.conversations(tenant, novel),
        "assets": await service.repository.assets(tenant, novel),
        "chapters": [{"id": str(row.id), "title": row.title, "chapter_index": row.chapter_index, "version": row.version,
                      "status": row.status, "content": row.content, "word_count": row.word_count} for row in value.chapters],
        "legacy_sources": legacy_sources(value),
        "enabled": settings.CONVERSATION_WORKBENCH_ENABLED,
    }


@router.post("/conversations", status_code=201)
async def create_conversation(novel_id: UUID, command: ConversationInput, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.repository.create_conversation(str(context.tenant_id), str(novel_id), command.title.strip() or "新对话"))


@router.get("/conversations/{conversation_id}")
async def get_conversation(novel_id: UUID, conversation_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    value = await service.repository.conversation(str(context.tenant_id), str(novel_id), str(conversation_id))
    if value is None:
        raise HTTPException(404, "对话不存在")
    return value


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(novel_id: UUID, conversation_id: UUID, command: ConversationInput, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.repository.rename_conversation(str(context.tenant_id), str(novel_id), str(conversation_id), command.title))


@router.post("/conversations/{conversation_id}/messages", status_code=202)
async def message(novel_id: UUID, conversation_id: UUID, command: MessageInput, key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
                  context=Depends(get_tenant_context), service=Depends(get_workbench)):
    allow_generation()
    snapshot = await invoke(service.snapshot(context, str(novel_id), str(conversation_id), command))
    job, created = await invoke(service.repository.create_job(str(context.tenant_id), str(novel_id), str(conversation_id), command, key, snapshot))
    if created:
        service.launch(context, str(novel_id), job["id"])
    return job


@router.get("/jobs/{job_id}")
async def get_job(novel_id: UUID, job_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    value = await service.repository.job(str(context.tenant_id), str(novel_id), str(job_id))
    if value is None:
        raise HTTPException(404, "任务不存在")
    return value


@router.get("/jobs/{job_id}/stream")
async def stream(novel_id: UUID, job_id: UUID, request: Request, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    if await service.repository.job(str(context.tenant_id), str(novel_id), str(job_id)) is None:
        raise HTTPException(404, "任务不存在")
    async def events():
        previous = None
        while not await request.is_disconnected():
            job = await service.repository.job(str(context.tenant_id), str(novel_id), str(job_id))
            if job is None:
                return
            encoded = json.dumps(job, ensure_ascii=False)
            if encoded != previous:
                yield f"event: snapshot\ndata: {encoded}\n\n"
                previous = encoded
            else:
                yield ": heartbeat\n\n"
            if job["status"] in TERMINAL:
                return
            await asyncio.sleep(0.4)
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/jobs/{job_id}/stop")
async def stop(novel_id: UUID, job_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.stop(context, str(novel_id), str(job_id)))


@router.post("/jobs/{job_id}/retry")
async def retry(novel_id: UUID, job_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    allow_generation()
    return await invoke(service.retry(context, str(novel_id), str(job_id)))


@router.post("/assets", status_code=201)
async def save_asset(novel_id: UUID, command: AssetInput, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.repository.save_asset(str(context.tenant_id), str(novel_id), command))


@router.patch("/assets/{asset_id}")
async def edit_asset(novel_id: UUID, asset_id: UUID, command: AssetEdit, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.repository.edit_asset(str(context.tenant_id), str(novel_id), str(asset_id), command))


@router.get("/assets/{asset_id}/versions")
async def versions(novel_id: UUID, asset_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await service.repository.asset_versions(str(context.tenant_id), str(novel_id), str(asset_id))


@router.post("/assets/{asset_id}/copy", status_code=201)
async def copy_asset(novel_id: UUID, asset_id: UUID, command: CopyInput, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    tenant = str(context.tenant_id)
    source = await service.repository.asset(tenant, str(novel_id), str(asset_id))
    if source is None or await service.novels.find_by_id(tenant, str(command.target_novel_id)) is None:
        raise HTTPException(404, "来源或目标作品不存在")
    if source["version"] != command.expected_version:
        raise HTTPException(409, "来源资产已变化，请重新载入")
    return await invoke(service.repository.save_asset(tenant, str(command.target_novel_id), AssetInput(
        title=source["title"], kind=source["kind"], content=source["content"],
    ), provenance={"source_novel_id": str(novel_id), "source_asset_id": str(asset_id), "source_version": source["version"]}))


@router.post("/assets/{asset_id}/review")
async def review(novel_id: UUID, asset_id: UUID, command: VersionInput, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    allow_generation()
    return await invoke(service.review(context, str(novel_id), str(asset_id), command.expected_version))


@router.post("/assets/{asset_id}/adopt")
async def adopt(novel_id: UUID, asset_id: UUID, command: AdoptInput, request: Request, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    allow_generation()
    result = await invoke(service.adopt(context, str(novel_id), str(asset_id), command))
    from application.checkpoint_reconciliation import reconcile_pending_checkpoint
    result["checkpoint_status"] = await reconcile_pending_checkpoint(service.novels, service.orchestrator, context, str(novel_id))
    return result


@router.get("/search")
async def search(novel_id: UUID, q: str = Query(min_length=1, max_length=2000), before_chapter: int | None = Query(default=None, ge=0),
                 context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return {"hits": await service.repository.search(str(context.tenant_id), str(novel_id), q, before_chapter), "available": True}


@router.post("/reindex")
async def reindex(novel_id: UUID, context=Depends(get_tenant_context), service=Depends(get_workbench)):
    return await invoke(service.repository.reindex(str(context.tenant_id), str(novel_id)))
