"""Tenant-scoped novel, chapter and rewrite endpoints."""

import asyncio
import inspect
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from api.dependencies import get_tenant_context
from api.workflow_commands import (
    ClaimedWorkflowCommand,
    claim_command,
    finalize_command_or_http,
    get_workflow_command_store,
    release_command_or_http,
)
from application.checkpoint_reconciliation import reconcile_pending_checkpoint
from application.errors import QualityGateReviewRequired, WorkflowBusyError
from application.feature_policy import feature_policy
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from application.tactical_planning import (
    hydrate_tactical_window,
    tactical_window_status,
)
from infrastructure.database.identity_repository import (
    AIUnavailableError,
    QuotaExceededError,
)
from infrastructure.database.repository import PostgresNovelRepository
from service.entities.identity import TenantContext
from service.entities.novel import Novel
from service.ports.workflow_command_store import WorkflowCommandStore
from service.value_objects.genre_profile import get_genre_taxonomy
from service.value_objects.novel_type import NovelType
from service.value_objects.outline import Outline
from service.value_objects.novel_plan import NovelPlan, ScaleContract, planning_options
from service.value_objects.progress import Progress
from service.value_objects.tactical_plan import TacticalWindow

router = APIRouter()
REWRITE_MAX_REVISION_ATTEMPTS = 5
REWRITE_MAX_NODE_STEPS = REWRITE_MAX_REVISION_ATTEMPTS * 2 + 2
_REWRITE_PERSISTENCE_STARTED = "_rewrite_persistence_started"


def get_repository(request: Request) -> PostgresNovelRepository:
    return request.app.state.repository


class NovelPlanningInput(BaseModel):
    preset: Literal["short", "medium", "long", "epic", "custom"]
    target_chapters: int = Field(ge=1, le=200)
    target_total_words: int

    @model_validator(mode="after")
    def validate_scale(self) -> "NovelPlanningInput":
        ScaleContract(
            preset=self.preset,
            target_chapters=self.target_chapters,
            target_total_words=self.target_total_words,
        )
        return self

    def to_contract(self) -> ScaleContract:
        return ScaleContract(
            preset=self.preset,
            target_chapters=self.target_chapters,
            target_total_words=self.target_total_words,
        )


class NovelCreateRequest(BaseModel):
    novel_type: str
    title: str | None = None
    summary: str | None = None
    total_outline: dict[str, Any] | None = None
    planning: NovelPlanningInput | None = None


class NovelResponse(BaseModel):
    id: str
    novel_type: str
    title: str | None
    summary: str | None
    status: str
    progress_percentage: float = 0.0
    thread_id: str | None = None
    total_outline: dict[str, Any] | None = None


class ProgressResponse(BaseModel):
    current_chapter: int
    total_chapters: int
    percentage: float
    status: str
    chapter_progress: dict[str, int | float]
    word_progress: dict[str, int | float]
    volume_progress: dict[str, int | float]
    plan_version: int = 0
    plan_status: str = "missing"
    drift_severity: str = "none"
    tactical_version: int | None = None
    tactical_window_start: int | None = None
    tactical_window_end: int | None = None
    tactical_status: Literal["active", "stale", "missing"] | None = None


class GenreOptionResponse(BaseModel):
    value: str
    label: str
    description: str = ""


class GenreProfileResponse(BaseModel):
    value: str
    label: str
    description: str
    subgenres: list[GenreOptionResponse]
    reader_experiences: list[GenreOptionResponse]
    pace_options: list[GenreOptionResponse]
    prompt_axes: dict[str, Any]


class ChapterResponse(BaseModel):
    id: str
    chapter_index: int
    title: str
    word_count: int
    status: str
    version: int
    review_status: Literal[
        "passed", "accepted_with_issues", "accepted_unreviewed", "unknown"
    ] = Field(default="unknown", description="章节质量审读状态")
    quality_score: float | None = Field(default=None, description="章节质量综合分")


class ChapterUpdateRequest(BaseModel):
    title: str = Field(max_length=255)
    content: str = Field(min_length=1)
    expected_version: int = Field(ge=1)


class ChapterDetailResponse(ChapterResponse):
    content: str
    updated_at: datetime
    checkpoint_status: str | None = None


class ChapterBatchDeleteRequest(BaseModel):
    chapter_ids: list[str] = Field(min_length=1)


def _tenant_id(context: TenantContext) -> str:
    return str(context.tenant_id)


def _novel_response(novel: Novel) -> NovelResponse:
    outline = novel.total_outline
    total_outline = (
        outline.__dict__
        if outline and hasattr(outline, "__dict__")
        else (outline if isinstance(outline, dict) else None)
    )
    return NovelResponse(
        id=str(novel.id),
        novel_type=novel.novel_type,
        title=novel.title,
        summary=novel.summary,
        status=novel.progress.status if novel.progress else "draft",
        progress_percentage=novel.progress.percentage if novel.progress else 0.0,
        thread_id=novel.thread_id,
        total_outline=total_outline,
    )


def _chapter_response(
    chapter: Any, checkpoint_status: str | None = None
) -> ChapterDetailResponse:
    return ChapterDetailResponse(
        id=str(chapter.id),
        chapter_index=chapter.chapter_index,
        title=chapter.title or f"第{chapter.chapter_index + 1}章",
        content=chapter.content or "",
        word_count=chapter.word_count,
        status=chapter.status,
        version=chapter.version,
        updated_at=chapter.updated_at,
        checkpoint_status=checkpoint_status,
        **_chapter_review_fields(chapter),
    )


def _chapter_review_fields(chapter: Any) -> dict[str, Any]:
    decision = chapter.user_decision if isinstance(chapter.user_decision, dict) else {}
    valid_statuses = {
        "passed", "accepted_with_issues", "accepted_unreviewed", "unknown",
    }
    status = decision.get("review_status", "unknown")
    if status == "pass":
        status = "passed"
    score = decision.get("quality_score")
    return {
        "review_status": status if status in valid_statuses else "unknown",
        "quality_score": (
            float(score)
            if isinstance(score, (int, float)) and not isinstance(score, bool)
            else None
        ),
    }


def _chapter_summary_response(chapter: Any) -> ChapterResponse:
    return ChapterResponse(
        id=str(chapter.id), chapter_index=chapter.chapter_index,
        title=chapter.title or f"第{chapter.chapter_index + 1}章",
        word_count=chapter.word_count, status=chapter.status, version=chapter.version,
        **_chapter_review_fields(chapter),
    )


def _workflow_busy_error(exc: WorkflowBusyError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={"code": "novel_busy", "message": str(exc)},
    )


@router.post("", response_model=dict, status_code=201)
async def create_novel(
    payload: NovelCreateRequest,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    try:
        valid_type = NovelType(payload.novel_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的小说类型") from exc
    outline, progress = _creation_outline_and_progress(payload)
    novel_id = uuid4()
    novel = Novel(
        id=novel_id,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        novel_type=valid_type.value,
        title=payload.title,
        summary=payload.summary,
        total_outline=outline,
        progress=progress,
        thread_id=str(novel_id),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    saved = await repo.save(_tenant_id(context), novel)
    return {
        "novel_id": str(saved.id),
        "thread_id": novel.thread_id,
        "status": "created",
    }


@router.get("", response_model=list[NovelResponse])
async def list_novels(
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    return [
        _novel_response(novel) for novel in await repo.find_all(_tenant_id(context))
    ]


@router.get("/genre-taxonomy", response_model=list[GenreProfileResponse])
async def genre_taxonomy(
    context: TenantContext = Depends(get_tenant_context),
) -> list[dict[str, Any]]:
    _tenant_id(context)
    return get_genre_taxonomy()


@router.get("/planning-options", response_model=dict[str, Any])
async def get_planning_options(
    context: TenantContext = Depends(get_tenant_context),
) -> dict[str, Any]:
    _tenant_id(context)
    return planning_options()


@router.get("/{novel_id}", response_model=NovelResponse)
async def get_novel(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return _novel_response(novel)


@router.get("/{novel_id}/plan", response_model=dict[str, Any] | None)
async def get_novel_plan(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if await repo.find_by_id(_tenant_id(context), novel_id) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    plan = await repo.get_latest_plan(_tenant_id(context), novel_id)
    if plan is None:
        return None
    payload = plan.to_dict()
    payload["executions"] = [
        item.to_dict()
        for item in await repo.list_plan_executions(_tenant_id(context), novel_id)
    ]
    return payload


@router.get("/{novel_id}/plan/versions", response_model=list[dict[str, Any]])
async def list_novel_plan_versions(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if await repo.find_by_id(_tenant_id(context), novel_id) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return await _plan_version_payloads(repo, _tenant_id(context), novel_id)


@router.get("/{novel_id}/tactical-plan", response_model=dict[str, Any])
async def get_tactical_plan(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
) -> dict[str, Any]:
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    plan = await repo.get_latest_plan(_tenant_id(context), novel_id)
    window = await repo.get_latest_tactical_plan(_tenant_id(context), novel_id)
    progress = novel.progress or Progress()
    status = _tactical_status(
        plan, window, progress.current_chapter, progress.plan_status
    )
    assembled = (
        hydrate_tactical_window(window, plan).get("beats", [])
        if status == "active" and window is not None and plan is not None
        else []
    )
    return {
        "status": status,
        "window": window.to_dict() if window else None,
        "assembled_slots": assembled,
    }


@router.get("/{novel_id}/tactical-plan/versions", response_model=list[dict[str, Any]])
async def list_tactical_plan_versions(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
) -> list[dict[str, Any]]:
    if await repo.find_by_id(_tenant_id(context), novel_id) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    windows = await repo.list_tactical_plan_versions(_tenant_id(context), novel_id)
    return [_tactical_version_summary(window) for window in windows]


@router.get("/{novel_id}/progress", response_model=ProgressResponse)
async def get_progress(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    progress = novel.progress or Progress()
    plan = await repo.get_latest_plan(_tenant_id(context), novel_id)
    tactical = await repo.get_latest_tactical_plan(_tenant_id(context), novel_id)
    return _progress_response(progress, plan, tactical)


@router.get("/{novel_id}/chapters", response_model=list[ChapterResponse])
async def list_chapters(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    novel = await repo.find_by_id_with_chapters(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return [_chapter_summary_response(chapter) for chapter in novel.chapters]


@router.get("/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def get_chapter(
    novel_id: str,
    chapter_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    if chapter is None or str(chapter.novel_id) != novel_id:
        raise HTTPException(status_code=404, detail="章节不存在")
    return _chapter_response(chapter)


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetailResponse)
async def update_chapter(
    novel_id: str,
    chapter_id: str,
    payload: ChapterUpdateRequest,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    try:
        async with orchestrator.exclusive_operation(
            context, novel_id, "正在保存章节修改"
        ):
            chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
            if chapter is None or str(chapter.novel_id) != novel_id:
                raise HTTPException(status_code=404, detail="章节不存在")
            chapter.title = (
                payload.title.strip()
                or chapter.title
                or f"第{chapter.chapter_index + 1}章"
            )
            chapter.content = payload.content
            chapter.word_count = len(payload.content)
            chapter.updated_at = datetime.now()
            memory = request.app.state.memory_service
            memory_content, memory_metadata = memory.build_chapter_memory(
                chapter.__dict__
            )
            saved = await repo.update_chapter_consistently(
                _tenant_id(context),
                novel_id,
                chapter,
                payload.expected_version,
                memory_content,
                memory_metadata,
                f"{chapter.title}\n\n{payload.content[:1200]}",
            )
            if saved is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "chapter_version_conflict",
                        "message": "章节已在其他窗口更新，请重新载入后再保存",
                    },
                )
            checkpoint_status = await reconcile_pending_checkpoint(
                repo, orchestrator, context, novel_id
            )
            return _chapter_response(saved, checkpoint_status)
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc


def _rewrite_config(
    request: Request,
    context: TenantContext,
    novel_id: str,
    repo: PostgresNovelRepository,
    quota: QuotaService,
    orchestrator: NovelOrchestrator,
) -> dict[str, Any]:
    return {
        "configurable": {
            "thread_id": f"{context.tenant_id}:{novel_id}",
            "public_thread_id": novel_id,
            "novel_id": novel_id,
            "tenant_id": _tenant_id(context),
            "tenant_context": context,
            "novel_repository": repo,
            "memory_service": request.app.state.memory_service,
            "quota_service": quota,
            "quota_operation_pre_reserved": True,
            "auto_mode": True,
            "direct_rewrite": True,
            "max_reflection_loops": REWRITE_MAX_REVISION_ATTEMPTS,
            "discard_following_chapters": False,
            "feature_policy": feature_policy,
            "novel_planning_v1_enabled": feature_policy.novel_planning_v1_enabled(
                context
            ),
            "tenant_planning_loader": orchestrator.tenant_planning_loader,
            "llm_config": {"llm_instance": orchestrator._get_llm_instance()},
        }
    }


def _rewrite_state(
    novel: Novel,
    chapter: Any,
    workflow_run_id: str,
    memory_context: str,
    plan: NovelPlan | None = None,
    tactical: TacticalWindow | None = None,
) -> dict[str, Any]:
    outline = novel.total_outline
    total_outline = (
        outline.__dict__
        if outline and hasattr(outline, "__dict__")
        else (outline if isinstance(outline, dict) else {})
    )
    return {
        "novel_type": novel.novel_type,
        "title": novel.title or "",
        "summary": novel.summary or "",
        "current_chapter_index": chapter.chapter_index,
        "chapter_outlines": [chapter.outline or {}],
        "total_outline": total_outline,
        "memory_context": memory_context,
        "current_chapter_content": "",
        "workflow_run_id": workflow_run_id,
        "workflow_schema_version": 5 if plan else 2,
        "novel_plan": plan.to_dict() if plan else None,
        "tactical_window": tactical.to_dict() if tactical else None,
        "rewrite_chapter_id": str(chapter.id),
        "rewrite_chapter_version": int(chapter.version),
        "rewrite_chapter_created_at": chapter.created_at,
    }


async def _generate_rewritten_chapter(
    state: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    await _run_rewrite_node("chapter_writer_node", state, config)
    if not state.get("current_chapter_content"):
        raise HTTPException(status_code=500, detail="章节内容生成失败")

    node_name = "reflection_node"
    for _ in range(REWRITE_MAX_NODE_STEPS):
        if node_name == "persist_node":
            state[_REWRITE_PERSISTENCE_STARTED] = True
        try:
            goto = await _run_rewrite_node(node_name, state, config)
        except QualityGateReviewRequired as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "quality_gate_not_met", "message": str(exc)},
            ) from exc
        if node_name == "persist_node":
            if state.get("novel_plan"):
                await _run_rewrite_node("plan_reconciliation_node", state, config)
                await _mark_rewrite_continuity_stale(config)
            return state
        allowed = {
            "reflection_node": {"persist_node", "revision_node"},
            "revision_node": {"reflection_node"},
        }
        if goto not in allowed[node_name]:
            raise HTTPException(status_code=500, detail="章节重写流程返回了无效状态")
        node_name = goto
    raise HTTPException(status_code=500, detail="章节重写超过最大修订次数")


async def _mark_rewrite_continuity_stale(config: dict[str, Any]) -> None:
    values = config.get("configurable", {})
    repository = values.get("novel_repository")
    marker = getattr(repository, "mark_continuity_reconciliation_needed", None)
    if callable(marker):
        await marker(values.get("tenant_id", ""), values.get("novel_id", ""))


async def _run_rewrite_node(
    node_name: str, state: dict[str, Any], config: dict[str, Any]
) -> str:
    from application.agents.chapter_writer_node import chapter_writer_node
    from application.agents.novel_plan_node import plan_reconciliation_node
    from application.agents.persist_node import persist_node
    from application.agents.reflection_node import reflection_node
    from application.agents.revision_node import revision_node

    nodes = {
        "chapter_writer_node": chapter_writer_node,
        "plan_reconciliation_node": plan_reconciliation_node,
        "reflection_node": reflection_node,
        "revision_node": revision_node,
        "persist_node": persist_node,
    }
    node = nodes.get(node_name)
    if node is None:
        raise HTTPException(status_code=500, detail="章节重写流程节点不存在")
    command = await node(state, config)
    state.update(command.update or {})
    if not isinstance(command.goto, str):
        raise HTTPException(status_code=500, detail="章节重写流程返回了无效路由")
    return command.goto


async def _load_rewrite_target(
    repo: PostgresNovelRepository,
    context: TenantContext,
    novel_id: str,
    chapter_id: str,
) -> tuple[Any, Novel]:
    chapter = await repo.find_chapter_by_id(_tenant_id(context), chapter_id)
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if chapter is None or str(chapter.novel_id) != novel_id or novel is None:
        raise HTTPException(status_code=404, detail="章节不存在")
    if not chapter.outline:
        raise HTTPException(status_code=400, detail="该章节没有细纲数据，无法重写")
    return chapter, novel


async def _reserve_rewrite(
    quota: QuotaService,
    context: TenantContext,
    workflow_run_id: UUID,
    chapter_index: int,
) -> None:
    try:
        await quota.reserve(context, workflow_run_id, "rewrite", chapter_index)
    except (QuotaExceededError, AIUnavailableError) as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "quota_exceeded", "message": str(exc)},
        ) from exc


async def _finish_rewrite(
    repo: PostgresNovelRepository,
    orchestrator: NovelOrchestrator,
    context: TenantContext,
    novel_id: str,
    state: dict[str, Any],
) -> ChapterDetailResponse:
    completed = state.get("completed_chapters", [])
    persisted_id = completed[-1].get("id") if completed else None
    persisted = (
        await repo.find_chapter_by_id(_tenant_id(context), persisted_id)
        if persisted_id
        else None
    )
    if persisted is None:
        raise HTTPException(status_code=500, detail="重写章节保存失败")
    checkpoint_status = await reconcile_pending_checkpoint(
        repo, orchestrator, context, novel_id
    )
    return _chapter_response(persisted, checkpoint_status)


def _rewrite_run_id(
    context: TenantContext, novel_id: str, command_id: str
) -> UUID:
    identity = f"{_tenant_id(context)}:{novel_id}:{command_id}"
    return uuid5(NAMESPACE_URL, f"novel-rewrite:{identity}")


async def _prepare_rewrite(
    request: Request,
    context: TenantContext,
    repo: PostgresNovelRepository,
    novel_id: str,
    chapter_id: str,
    command: ClaimedWorkflowCommand,
) -> tuple[dict[str, Any], dict[str, Any]]:
    quota: QuotaService = request.app.state.quota_service
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    chapter, novel = await _load_rewrite_target(
        repo, context, novel_id, chapter_id
    )
    run_id = _rewrite_run_id(context, novel_id, command.command_id)
    await _reserve_rewrite(quota, context, run_id, chapter.chapter_index)
    memory = await request.app.state.memory_service.get_hierarchical_context(
        _tenant_id(context), novel_id, chapter.chapter_index
    )
    plan = await _optional_latest_plan(repo, _tenant_id(context), novel_id)
    tactical = await _rewrite_tactical_window(
        repo, _tenant_id(context), novel_id, chapter, plan
    )
    state = _rewrite_state(novel, chapter, str(run_id), memory, plan, tactical)
    config = _rewrite_config(request, context, novel_id, repo, quota, orchestrator)
    return state, config


async def _optional_latest_plan(
    repo: Any, tenant_id: str, novel_id: str
) -> NovelPlan | None:
    getter = getattr(repo, "get_latest_plan", None)
    if not callable(getter):
        return None
    result = getter(tenant_id, novel_id)
    resolved = await result if inspect.isawaitable(result) else result
    return resolved if isinstance(resolved, NovelPlan) else None


async def _rewrite_tactical_window(
    repo: Any,
    tenant_id: str,
    novel_id: str,
    chapter: Any,
    plan: NovelPlan | None,
) -> TacticalWindow | None:
    chapter_outline = getattr(chapter, "outline", None)
    outline = chapter_outline if isinstance(chapter_outline, dict) else {}
    contract = outline.get("chapter_execution_contract")
    if plan is None or not isinstance(contract, dict):
        return None
    try:
        version = int(contract.get("tactical_version", 0) or 0)
    except (TypeError, ValueError):
        return None
    getter = getattr(repo, "list_tactical_plan_versions", None)
    if version < 1 or not callable(getter):
        return None
    windows = await getter(tenant_id, novel_id)
    return next(
        (
            window for window in windows
            if window.version == version
            and window.novel_plan_version == plan.version
        ),
        None,
    )


async def _plan_version_payloads(
    repo: Any, tenant_id: str, novel_id: str
) -> list[dict[str, Any]]:
    summary_getter = getattr(repo, "list_plan_version_summaries", None)
    if callable(summary_getter):
        summaries = await summary_getter(tenant_id, novel_id)
        return [summary.to_dict() for summary in summaries]
    plans = await repo.list_plan_versions(tenant_id, novel_id)
    return [
        {
            "version": plan.version,
            "source": plan.source,
            "trigger_chapter": None,
            "change_summary": "",
            "created_by_user_id": None,
            "created_at": plan.created_at.isoformat(),
        }
        for plan in plans
    ]


def _creation_outline_and_progress(
    payload: NovelCreateRequest,
) -> tuple[Outline | None, Progress]:
    outline_data = dict(payload.total_outline or {})
    contract = payload.planning.to_contract() if payload.planning else None
    if contract is None:
        total = int(outline_data.get("total_chapters", 0) or 0)
        if 1 <= total <= 200:
            raw_scale = outline_data.get("scale")
            target_words = (
                int(raw_scale.get("target_total_words", 0) or 0)
                if isinstance(raw_scale, dict)
                else 0
            )
            contract = ScaleContract(
                preset="custom",
                target_chapters=total,
                target_total_words=target_words or total * 4200,
            )
    if contract:
        outline_data.update(
            total_chapters=contract.target_chapters,
            scale=contract.to_dict(),
        )
    outline = Outline(**outline_data) if outline_data else None
    return outline, Progress(
        total_chapters=contract.target_chapters if contract else 0,
        target_words=contract.target_total_words if contract else 0,
        plan_status="pending" if contract else "missing",
    )


def _volume_progress(plan: NovelPlan | None, current: int) -> dict[str, int | float]:
    if plan is None or not plan.volumes:
        return {"current": 0, "total": 0, "percentage": 0.0}
    chapter = min(max(current + 1, 1), plan.scale.target_chapters)
    volume = next(
        (
            item for item in plan.volumes
            if item.start_chapter <= chapter <= item.end_chapter
        ),
        plan.volumes[-1],
    )
    number = plan.volumes.index(volume) + 1
    length = volume.end_chapter - volume.start_chapter + 1
    completed = max(0, min(current, volume.end_chapter) - volume.start_chapter + 1)
    return {
        "current": number,
        "total": len(plan.volumes),
        "percentage": completed / length * 100 if length else 0.0,
    }


def _tactical_status(
    plan: NovelPlan | None,
    window: TacticalWindow | None,
    completed_chapters: int,
    plan_status: str = "accepted",
) -> Literal["active", "stale", "missing"]:
    if plan is None or window is None:
        return "missing"
    if plan_status in {"needs_reconciliation", "needs_review"}:
        return "stale"
    chapter = min(max(completed_chapters + 1, 1), plan.scale.target_chapters)
    return tactical_window_status(window, plan, chapter, completed_chapters)


def _tactical_version_summary(window: TacticalWindow) -> dict[str, Any]:
    return {
        "version": window.version,
        "novel_plan_version": window.novel_plan_version,
        "story_state_revision": window.story_state_revision,
        "start_chapter": window.start_chapter,
        "end_chapter": window.end_chapter,
        "source": window.source,
        "created_at": window.created_at.isoformat(),
    }


def _progress_response(
    progress: Progress,
    plan: NovelPlan | None,
    tactical: TacticalWindow | None = None,
) -> ProgressResponse:
    total_chapters = (
        plan.scale.target_chapters if plan else progress.total_chapters
    )
    target_words = plan.scale.target_total_words if plan else progress.target_words
    chapter_percentage = (
        progress.current_chapter / total_chapters * 100 if total_chapters else 0.0
    )
    return ProgressResponse(
        current_chapter=progress.current_chapter,
        total_chapters=total_chapters,
        percentage=chapter_percentage,
        status=progress.status,
        chapter_progress={
            "current": progress.current_chapter,
            "total": total_chapters,
            "percentage": chapter_percentage,
        },
        word_progress={
            "current": progress.completed_words,
            "target": target_words,
            "percentage": (
                progress.completed_words / target_words * 100
                if target_words
                else 0.0
            ),
        },
        volume_progress=_volume_progress(plan, progress.current_chapter),
        plan_version=plan.version if plan else progress.plan_version,
        plan_status=(
            progress.plan_status
            if not plan or progress.plan_status != "missing"
            else "accepted"
        ),
        drift_severity=progress.drift_severity,
        tactical_version=tactical.version if tactical else None,
        tactical_window_start=tactical.start_chapter if tactical else None,
        tactical_window_end=tactical.end_chapter if tactical else None,
        tactical_status=_tactical_status(
            plan, tactical, progress.current_chapter, progress.plan_status
        ),
    )


async def _release_replayable_rewrite(
    store: WorkflowCommandStore,
    context: TenantContext,
    novel_id: str,
    command: ClaimedWorkflowCommand,
    state: dict[str, Any] | None,
) -> None:
    if state and state.get(_REWRITE_PERSISTENCE_STARTED):
        return
    await release_command_or_http(store, context, novel_id, command)


async def _execute_rewrite_command(
    request: Request,
    context: TenantContext,
    repo: PostgresNovelRepository,
    novel_id: str,
    chapter_id: str,
    command: ClaimedWorkflowCommand,
    store: WorkflowCommandStore,
) -> ChapterDetailResponse:
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    state: dict[str, Any] | None = None
    try:
        async with orchestrator.exclusive_operation(context, novel_id, "正在重写章节"):
            state, config = await _prepare_rewrite(
                request, context, repo, novel_id, chapter_id, command
            )
            state = await _generate_rewritten_chapter(state, config)
            response = await _finish_rewrite(
                repo, orchestrator, context, novel_id, state
            )
    except (Exception, asyncio.CancelledError):
        await _release_replayable_rewrite(
            store, context, novel_id, command, state
        )
        raise
    await finalize_command_or_http(store, context, novel_id, command)
    return response


@router.post(
    "/{novel_id}/chapters/{chapter_id}/rewrite",
    response_model=ChapterDetailResponse,
)
async def rewrite_chapter(
    novel_id: str,
    chapter_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
    store: WorkflowCommandStore = Depends(get_workflow_command_store),
) -> ChapterDetailResponse:
    command = await claim_command(store, context, novel_id, idempotency_key)
    try:
        return await _execute_rewrite_command(
            request, context, repo, novel_id, chapter_id, command, store
        )
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc


@router.delete("/{novel_id}")
async def delete_novel(
    novel_id: str,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if not context.can_delete_content():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    novel = await repo.find_by_id(_tenant_id(context), novel_id)
    if novel is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    await repo.delete(_tenant_id(context), novel_id)
    return {"status": "deleted", "novel_id": novel_id}


@router.post("/{novel_id}/chapters/batch-delete")
async def batch_delete_chapters(
    novel_id: str,
    payload: ChapterBatchDeleteRequest,
    request: Request,
    context: TenantContext = Depends(get_tenant_context),
    repo: PostgresNovelRepository = Depends(get_repository),
):
    if not context.can_delete_content():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    orchestrator: NovelOrchestrator = request.app.state.orchestrator
    try:
        async with orchestrator.exclusive_operation(context, novel_id, "正在回退章节"):
            deleted, rewind_to = await repo.rewind_chapters_atomically(
                _tenant_id(context), novel_id, payload.chapter_ids
            )
            if rewind_to is None:
                raise HTTPException(status_code=404, detail="未找到可回退的章节")
            checkpoint_status = await reconcile_pending_checkpoint(
                repo, orchestrator, context, novel_id
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="章节 ID 格式不正确") from exc
    except WorkflowBusyError as exc:
        raise _workflow_busy_error(exc) from exc
    return {
        "status": "rewound",
        "count": deleted,
        "rewind_to": rewind_to,
        "checkpoint_status": checkpoint_status,
    }
