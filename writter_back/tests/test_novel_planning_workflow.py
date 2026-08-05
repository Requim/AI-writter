"""整书规划 v1 的工作流、局部上下文与漂移策略测试。"""

from __future__ import annotations

from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from api.routers import workflow_router
from api.routers.workflow_router import WorkflowInvokeRequest, _prepare_request
from application.agents.novel_plan_node import (
    novel_plan_finalize_node,
    novel_plan_initialize_node,
    novel_plan_review_node,
    novel_plan_volume_node,
    plan_reconciliation_node,
)
from application.agents.router_agent import _route
from application.planning import select_plan_context
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.prompts.novel_plan_prompts import BLUEPRINT_SCHEMA, VOLUME_SLOTS_SCHEMA
from service.entities.identity import TenantContext
from service.value_objects.novel_plan import NovelPlan, ScaleContract
from service.value_objects.progress import Progress


def _ranges(chapters: int) -> list[tuple[int, int]]:
    return [
        (start, min(start + 24, chapters))
        for start in range(1, chapters + 1, 25)
    ]


class PlanningLLM:
    def __init__(self, chapters: int, words: int, invalid_blueprints: int = 0):
        self.chapters = chapters
        self.words = words
        self.invalid_blueprints = invalid_blueprints
        self.blueprint_calls = 0
        self.volume_calls = 0
        self.fail_volume_call: int | None = None

    async def structured_generate(self, _prompt, schema, **_kwargs):
        if schema is BLUEPRINT_SCHEMA:
            self.blueprint_calls += 1
            invalid = self.blueprint_calls <= self.invalid_blueprints
            return self._blueprint(invalid)
        if schema is VOLUME_SLOTS_SCHEMA:
            self.volume_calls += 1
            if self.fail_volume_call == self.volume_calls:
                self.volume_calls -= 1
                raise RuntimeError("provider unavailable")
            return self._volume_slots(self.volume_calls - 1)
        raise AssertionError(f"unexpected schema: {schema}")

    def _blueprint(self, invalid: bool = False) -> dict:
        volumes = []
        for index, (start, end) in enumerate(_ranges(self.chapters), start=1):
            volumes.append({
                "volume_id": f"volume-{index}", "title": f"第{index}卷",
                "start_chapter": start + int(invalid and index == 1), "end_chapter": end,
                "target_words": 0, "opening_state": "压力建立", "midpoint_turn": "认知逆转",
                "climax": "冲突兑现", "ending_state": "代价落定",
                "reader_promises": ["推进主线"], "setup_ids": [], "payoff_ids": [],
            })
        return {
            "scale": ScaleContract("custom", self.chapters, self.words).to_dict(),
            "ending_contract": {"final_state": "核心问题获得不可逆答案"},
            "volumes": volumes,
            "arcs": [{
                "arc_id": "arc-main", "arc_type": "主线", "start_chapter": 1,
                "end_chapter": self.chapters, "goal": "完成核心目标",
                "escalation_points": [{"chapter_number": max(1, self.chapters // 2), "change": "升级"}],
                "resolution_condition": "最终章完成选择并承担代价", "is_core": True,
            }],
        }

    def _volume_slots(self, index: int) -> dict:
        start, end = _ranges(self.chapters)[index]
        return {"chapter_slots": [self._slot(number, index + 1) for number in range(start, end + 1)]}

    @staticmethod
    def _slot(number: int, volume: int) -> dict:
        return {
            "chapter_number": number, "volume_id": f"volume-{volume}",
            "arc_ids": ["arc-main"], "story_function": f"推进阶段 {number}",
            "must_happen": [f"事件-{number}"], "planned_state_delta": f"状态-{number}",
            "setup_ids": [], "payoff_ids": [], "intensity_weight": 1 + number % 4,
        }


class PlanRepository:
    def __init__(self, legacy_chapters: list | None = None):
        self.latest: NovelPlan | None = None
        self.executions = []
        self.legacy_chapters = legacy_chapters or []
        self.idempotency_keys: list[str] = []

    async def accept_plan(self, _tenant, _novel, plan, expected, **kwargs):
        current = self.latest.version if self.latest else 0
        assert current == expected
        self.idempotency_keys.append(kwargs["idempotency_key"])
        self.latest = replace(plan, version=expected + 1)
        return self.latest

    async def upsert_plan_execution(self, _tenant, _novel, execution):
        self.executions.append(execution)
        return execution

    async def find_by_id_with_chapters(self, _tenant, _novel):
        return SimpleNamespace(chapters=self.legacy_chapters)


def _config(llm: PlanningLLM, repository: PlanRepository, auto: bool = True) -> dict:
    return {"configurable": {
        "llm_config": {"llm_instance": llm}, "novel_repository": repository,
        "tenant_id": str(uuid4()), "novel_id": str(uuid4()), "auto_mode": auto,
        "novel_planning_v1_enabled": True,
    }}


def _state(chapters: int, words: int, current: int = 0) -> dict:
    scale = ScaleContract("custom", chapters, words)
    return {
        "novel_type": "suspense", "title": "雨夜回信",
        "total_outline": {"total_chapters": chapters, "scale": scale.to_dict()},
        "scale_contract": scale.to_dict(), "current_chapter_index": current,
        "proposal_versions": {}, "workflow_schema_version": 5,
    }


async def _generated_plan(
    chapters: int, words: int, *, current: int = 0, legacy: list | None = None,
) -> tuple[NovelPlan, PlanningLLM, PlanRepository, dict]:
    llm = PlanningLLM(chapters, words)
    repository = PlanRepository(legacy)
    state = _state(chapters, words, current)
    config = _config(llm, repository)
    command = await novel_plan_initialize_node(state, config)
    state.update(command.update)
    while command.goto == "novel_plan_volume_node":
        command = await novel_plan_volume_node(state, config)
        state.update(command.update)
    command = await novel_plan_finalize_node(state, config)
    state.update(command.update)
    if current:
        proposal = state["pending_proposal"]
        state["pending_proposal_decision"] = {
            "proposal_id": proposal["proposal_id"], "decision": "accept",
        }
    proposal_id = state["pending_proposal"]["proposal_id"]
    command = await novel_plan_review_node(state, config)
    state.update(command.update)
    assert repository.idempotency_keys[-1] == proposal_id
    return NovelPlan.from_dict(state["novel_plan"]), llm, repository, state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chapters", "words"), [(12, 50_400), (80, 336_000), (200, 840_000)],
)
async def test_initial_plan_closes_scale_for_12_80_and_200_chapters(
    chapters: int, words: int,
) -> None:
    plan, llm, _repository, _state_value = await _generated_plan(chapters, words)
    assert len(plan.chapter_slots) == chapters
    assert sum(slot.target_words for slot in plan.chapter_slots) == words
    assert llm.volume_calls == len(_ranges(chapters))
    assert all(slot.detail_level == "detailed" for slot in plan.chapter_slots[:25])
    assert all(slot.detail_level == "skeleton" for slot in plan.chapter_slots[25:])
    plan.assert_valid()


@pytest.mark.asyncio
async def test_blueprint_retries_with_business_validation_feedback() -> None:
    llm = PlanningLLM(12, 50_400, invalid_blueprints=1)
    state = _state(12, 50_400)
    command = await novel_plan_initialize_node(state, _config(llm, PlanRepository()))
    assert command.goto == "novel_plan_volume_node"
    assert llm.blueprint_calls == 2


@pytest.mark.asyncio
async def test_volume_checkpoint_resumes_from_failed_unfinished_volume() -> None:
    llm = PlanningLLM(80, 336_000)
    state = _state(80, 336_000)
    config = _config(llm, PlanRepository())
    command = await novel_plan_initialize_node(state, config)
    state.update(command.update)
    first = await novel_plan_volume_node(state, config)
    state.update(first.update)
    first_slots = list(state["plan_generation"]["chapter_slots"])
    llm.fail_volume_call = 2
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await novel_plan_volume_node(state, config)
    llm.fail_volume_call = None
    resumed = await novel_plan_volume_node(state, config)
    state.update(resumed.update)
    assert state["plan_generation"]["chapter_slots"][:25] == first_slots
    assert state["plan_generation"]["next_volume_index"] == 2


@pytest.mark.asyncio
async def test_legacy_upgrade_locks_completed_slots_and_forces_review() -> None:
    legacy = [
        SimpleNamespace(chapter_index=index, title=f"旧章{index + 1}", word_count=4000,
                        outline={"chapter_goal": f"既成事实{index + 1}", "key_events": ["已发生"]})
        for index in range(2)
    ]
    plan, _llm, _repository, state = await _generated_plan(
        12, 50_400, current=2, legacy=legacy,
    )
    assert state["plan_generation"] is None
    assert [slot.status for slot in plan.chapter_slots[:2]] == ["completed", "completed"]
    assert [slot.story_function for slot in plan.chapter_slots[:2]] == ["既成事实1", "既成事实2"]
    assert plan.source == "legacy_upgrade"


@pytest.mark.asyncio
async def test_minor_drift_auto_reschedules_only_outside_lock_window() -> None:
    plan, _llm, repository, _state_value = await _generated_plan(12, 50_400)
    repository.latest = plan
    original = {slot.chapter_number: asdict(slot) for slot in plan.chapter_slots}
    fulfillment = {"deferred_items": ["延后线索"], "state_delta_fulfilled": True}
    state = _reconciliation_state(plan, fulfillment)
    command = await plan_reconciliation_node(state, _config(PlanningLLM(12, 50_400), repository))
    accepted = NovelPlan.from_dict(command.update["novel_plan"])
    assert command.goto == "progress_check_node" and accepted.version == 2
    assert repository.idempotency_keys[-1] == "auto-drift:plan:1:chapter:1"
    assert all(asdict(accepted.chapter_slots[index - 1]) == original[index] for index in range(1, 7))
    assert "延后线索" in accepted.chapter_slots[6].must_happen


def _reconciliation_state(plan: NovelPlan, fulfillment: dict) -> dict:
    target = plan.chapter_slots[0].target_words
    return {
        "novel_plan": plan.to_dict(), "current_chapter_index": 1,
        "last_persisted_chapter": {"word_count": target},
        "quality_gate": {"plan_fulfillment": fulfillment}, "proposal_versions": {},
        "workflow_schema_version": 5,
    }


@pytest.mark.asyncio
async def test_major_drift_always_enters_human_replanning_path() -> None:
    plan, _llm, repository, _state_value = await _generated_plan(12, 50_400)
    repository.latest = plan
    state = _reconciliation_state(plan, {"core_arc_breached": True})
    command = await plan_reconciliation_node(
        state, _config(PlanningLLM(12, 50_400), repository, auto=True)
    )
    request = command.update["plan_replan_request"]
    assert command.goto == "novel_plan_initialize_node"
    assert request["trigger"] == "drift" and request["expected_version"] == 1


@pytest.mark.asyncio
async def test_chapter_prompt_receives_only_local_plan_slice() -> None:
    plan, _llm, _repository, _state_value = await _generated_plan(12, 50_400)
    plan.chapter_slots[9].must_happen = ["绝不能出现在第一章提示词的远期秘密"]
    context = select_plan_context(plan, 1)
    prompt = build_chapter_outline_prompt(
        1, "suspense", "雨夜回信", {"total_chapters": 12}, "", plan_context=context,
    )
    assert len(context["future_slots"]) == 4
    assert "绝不能出现在第一章提示词的远期秘密" not in prompt
    assert context["current_slot"]["target_words"] in range(3000, 7001)
    assert "ending_contract" not in context
    assert select_plan_context(plan, 12)["ending_contract"] == plan.ending_contract
    assert "scale" in BLUEPRINT_SCHEMA


@pytest.mark.asyncio
async def test_planning_flag_uses_schema_five_and_missing_plan_route(monkeypatch) -> None:
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    repository = SimpleNamespace(get_latest_plan=AsyncMock(return_value=None))
    service = SimpleNamespace(
        repository=repository, set_auto_mode=lambda *_args: None,
        get_workflow_run_id=AsyncMock(return_value=None),
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    prepared, *_ = await _prepare_request(
        WorkflowInvokeRequest(input={}), _tenant_context(planning=True), str(uuid4()), service, quota,
    )
    assert prepared["workflow_schema_version"] == 5
    assert _route({
        "total_outline": {"total_chapters": 12},
        "workflow_schema_version": 5,
    })[0] == "novel_plan_initialize_node"


@pytest.mark.asyncio
async def test_persisted_major_drift_forces_human_replanning(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True
    )
    plan, _llm, _repository, _state_value = await _generated_plan(12, 50_400)
    plan = replace(plan, version=3)
    repository = SimpleNamespace(get_latest_plan=AsyncMock(return_value=plan))
    service = SimpleNamespace(
        repository=repository,
        set_auto_mode=lambda *_args: None,
        get_workflow_run_id=AsyncMock(return_value="existing-run"),
    )
    novel = SimpleNamespace(
        novel_type="suspense",
        progress=Progress(
            current_chapter=4,
            total_chapters=12,
            plan_version=3,
            plan_status="needs_review",
            drift_severity="major",
        ),
        title="雨夜回信",
        summary="",
        total_outline=None,
    )

    prepared, *_ = await _prepare_request(
        WorkflowInvokeRequest(input={}),
        _tenant_context(planning=True),
        str(uuid4()),
        service,
        SimpleNamespace(reserve=AsyncMock()),
        novel,
    )

    assert prepared["story_state_needs_reconciliation"] is True
    assert prepared["plan_replan_request"] == {
        "expected_version": 3,
        "scope": "future",
        "instruction": "根据已记录的重大结构偏差重排未来计划",
        "trigger": "drift",
    }


@pytest.mark.asyncio
async def test_user_replan_rejects_stale_expected_version(monkeypatch) -> None:
    monkeypatch.setattr("api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True)
    plan, _llm, _repository, _state_value = await _generated_plan(12, 50_400)
    plan = replace(plan, version=2)
    repository = SimpleNamespace(get_latest_plan=AsyncMock(return_value=plan))
    service = SimpleNamespace(
        repository=repository, set_auto_mode=lambda *_args: None,
        get_workflow_run_id=AsyncMock(return_value=None),
    )
    request = WorkflowInvokeRequest(command={"plan_replan": {
        "expected_version": 1,
        "scope": "future",
        "instruction": "调整后续节奏",
    }})

    with pytest.raises(HTTPException) as raised:
        await _prepare_request(
            request, _tenant_context(planning=True), str(uuid4()), service,
            SimpleNamespace(reserve=AsyncMock()),
        )
    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "plan_version_conflict"


@pytest.mark.asyncio
async def test_replan_ignores_client_supplied_workflow_run_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True
    )
    plan, _llm, _repository, _state_value = await _generated_plan(12, 50_400)
    repository = SimpleNamespace(get_latest_plan=AsyncMock(return_value=plan))
    service = SimpleNamespace(
        repository=repository,
        set_auto_mode=lambda *_args: None,
        get_workflow_run_id=AsyncMock(return_value="trusted-existing-run"),
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    malicious = "00000000-0000-0000-0000-000000000001"
    request = WorkflowInvokeRequest(
        input={"workflow_run_id": malicious},
        command={"plan_replan": {
            "expected_version": plan.version,
            "scope": "future",
            "instruction": "调整节奏",
        }},
    )

    prepared, *_ = await _prepare_request(
        request,
        _tenant_context(planning=True),
        str(uuid4()),
        service,
        quota,
        command_id="server-command",
    )

    assert prepared["workflow_run_id"] != malicious
    assert prepared["workflow_run_id"] != "trusted-existing-run"
    assert quota.reserve.await_args.args[1] == prepared["workflow_run_id"]


@pytest.mark.asyncio
async def test_disabled_schema_five_rejects_before_checkpoint_reconciliation(
    monkeypatch,
) -> None:
    checkpoint_ready = AsyncMock()
    monkeypatch.setattr(
        workflow_router,
        "_authorize_thread",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        workflow_router,
        "_claim_command",
        AsyncMock(return_value=SimpleNamespace(command_id="command-1")),
    )
    monkeypatch.setattr(workflow_router, "_acquire", AsyncMock())
    monkeypatch.setattr(workflow_router, "_ensure_checkpoint_ready", checkpoint_ready)
    monkeypatch.setattr(workflow_router, "_release_command_or_http", AsyncMock())
    orchestrator = SimpleNamespace(
        set_active_command=lambda *_args: None,
        get_workflow_schema_version=AsyncMock(return_value=5),
        finish=lambda *_args: None,
    )

    with pytest.raises(HTTPException) as raised:
        await workflow_router._prepare_execution(
            str(uuid4()),
            WorkflowInvokeRequest(input={}),
            "command-key",
            _tenant_context(planning=False),
            orchestrator,
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        )

    assert raised.value.detail["code"] == "planning_temporarily_disabled"
    checkpoint_ready.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_five_checkpoint_pauses_when_effective_flag_is_off(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", False
    )
    service = SimpleNamespace(
        get_workflow_schema_version=AsyncMock(return_value=5),
        set_auto_mode=lambda *_args: None,
    )
    quota = SimpleNamespace(reserve=AsyncMock())
    with pytest.raises(HTTPException) as raised:
        await _prepare_request(
            WorkflowInvokeRequest(input={}),
            _tenant_context(planning=True),
            str(uuid4()),
            service,
            quota,
        )
    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "planning_temporarily_disabled"
    quota.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_legacy_novel_does_not_trigger_plan_upgrade_quota(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "api.routers.workflow_router.settings.NOVEL_PLANNING_V1_ENABLED", True
    )
    novel = SimpleNamespace(progress=SimpleNamespace(is_complete=lambda: True))
    service = SimpleNamespace(
        get_workflow_schema_version=AsyncMock(return_value=None),
        set_auto_mode=lambda *_args: None,
    )
    quota = SimpleNamespace(reserve=AsyncMock())

    with pytest.raises(HTTPException) as raised:
        await _prepare_request(
            WorkflowInvokeRequest(input={}),
            _tenant_context(planning=True),
            str(uuid4()),
            service,
            quota,
            novel,
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["code"] == "novel_completed"
    quota.reserve.assert_not_awaited()


def _tenant_context(*, planning: bool = False) -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(), tenant_name="测试租户", user_id=uuid4(),
        role="owner", is_platform_admin=False, ai_enabled=True,
        monthly_generation_limit=30,
        novel_planning_v1_enabled=planning,
    )
