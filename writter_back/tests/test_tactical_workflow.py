"""Schema 5 rolling tactics and combined chapter-plan workflow tests."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.agents.chapter_outline_node import (
    _regenerate_chapter_plan,
    chapter_outline_node,
    chapter_plan_review_node,
)
from application.agents.chapter_quota_node import chapter_quota_node
from application.agents.router_agent import _route, router_agent
from application.agents.tactical_plan_node import tactical_plan_node
from application.prompts.chapter_outline_prompts import CHAPTER_OUTLINE_SCHEMA
from application.prompts.tactical_plan_prompts import TACTICAL_WINDOW_SCHEMA
from application.errors import InvalidReviewDecisionError
from application.planning import classify_drift
from application.proposals import create_proposal, parse_review_decision
from service.value_objects.novel_plan import (
    ChapterSlot,
    NovelPlan,
    ScaleContract,
    StoryArc,
    VolumePlan,
)
from service.value_objects.tactical_plan import TacticalWindow


def _plan() -> NovelPlan:
    slots = [
        ChapterSlot(
            chapter_number=number,
            volume_id="v1",
            arc_ids=["main"],
            story_function=f"推进阶段 {number}",
            must_happen=[f"事件 {number}"],
            planned_state_delta=f"状态变化 {number}",
            target_words=4200,
            setup_ids=["clue-1"] if number == 1 else [],
            payoff_ids=["clue-1"] if number == 3 else [],
            detail_level="detailed",
        )
        for number in range(1, 13)
    ]
    return NovelPlan(
        scale=ScaleContract("short", 12, 50_400),
        ending_contract={"final_state": "真相公开"},
        volumes=[VolumePlan(
            "v1", "第一卷", 1, 12, 50_400,
            "收到来信", "确认威胁", "证据反转", "决定追查",
        )],
        arcs=[StoryArc(
            "main", "mystery", 1, 12, "查清真相",
            [{"chapter_number": 3, "event": "第一次升级"}],
            "最终章公开真相", True,
        )],
        chapter_slots=slots,
        version=1,
    )


def _outline() -> dict:
    return {
        "chapter_number": 1,
        "title": "雨夜来信",
        "chapter_goal": "主角决定核验来信",
        "key_events": ["收到来信", "核验笔迹"],
        "entry_state": {"time": "雨夜"},
        "exit_state": {"last_action": "带走来信"},
        "causal_chain": ["收到信", "发现笔迹", "决定调查"],
        "scenes": [{"events": {}}, {"events": {}}],
        "chapter_execution_contract": {
            "obligation_coverage": {"ch1:must:1": 1},
            "state_delta_coverage": {"ch1:state_delta": 2},
            "setup_payoff_coverage": {"ch1:setup:clue-1": 1},
        },
        "estimated_word_count": 4200,
    }


class TacticalWorkflowLLM:
    def __init__(self, invalid_tactical: int = 0) -> None:
        self.invalid_tactical = invalid_tactical
        self.tactical_calls = 0
        self.prompts: list[str] = []

    async def structured_generate(self, prompt, schema, **_kwargs):
        self.prompts.append(prompt)
        if schema is CHAPTER_OUTLINE_SCHEMA:
            return _outline()
        assert schema is TACTICAL_WINDOW_SCHEMA
        self.tactical_calls += 1
        if self.tactical_calls <= self.invalid_tactical:
            return {"window_objective": "无效", "beats": []}
        return {
            "window_objective": "在第三章前确认来信来自内部",
            "beats": [
                {
                    "chapter_number": number,
                    "slot_ref": f"ch{number}",
                    "tactical_goal": f"推进线索 {number}",
                    "approach": "核验并反向追踪",
                    "bridge_from_previous": "承接当前事实",
                    "pressure_escalation": "对手主动销毁证据",
                    "exit_hook": "发现下一处可调查目标",
                    "pacing": "调查与反制交替",
                }
                for number in range(1, 4)
            ],
        }


class TacticalRepository:
    def __init__(self) -> None:
        self.latest = None
        self.accept_calls = 0
        self.idempotency_keys: list[str] = []

    async def get_latest_tactical_plan(self, _tenant_id, _novel_id):
        return self.latest

    async def accept_tactical_plan(
        self, _tenant_id, _novel_id, window, expected_version, *,
        idempotency_key, **_kwargs,
    ):
        assert expected_version == (self.latest.version if self.latest else 0)
        self.accept_calls += 1
        self.idempotency_keys.append(idempotency_key)
        self.latest = replace(window, version=expected_version + 1)
        return self.latest


def _state(plan: NovelPlan) -> dict:
    return {
        "workflow_schema_version": 5,
        "novel_plan": plan.to_dict(),
        "total_outline": {
            "total_chapters": 12,
            "story_background": "当代城市",
            "main_plot": {"opening": "收到来信", "ending": "公开真相"},
        },
        "novel_type": "suspense",
        "title": "雨夜回信",
        "current_chapter_index": 0,
        "chapter_outlines": [],
        "proposal_versions": {},
        "memory_context": "尚未完成任何章节",
    }


def _config(llm, repository, *, auto: bool = False) -> dict:
    return {"configurable": {
        "llm_config": {"llm_instance": llm},
        "novel_repository": repository,
        "tenant_id": str(uuid4()),
        "novel_id": str(uuid4()),
        "tenant_context": SimpleNamespace(user_id=uuid4()),
        "auto_mode": auto,
        "novel_planning_v1_enabled": True,
    }}


@pytest.mark.asyncio
async def test_tactical_generation_retries_validation_and_stays_bounded() -> None:
    plan = _plan()
    plan.chapter_slots[9].must_happen = ["不得进入近期提示词的远期秘密"]
    llm, repository = TacticalWorkflowLLM(invalid_tactical=1), TacticalRepository()
    command = await tactical_plan_node(_state(plan), _config(llm, repository))

    assert command.goto == "chapter_outline_node"
    assert llm.tactical_calls == 2
    assert command.update["tactical_window"]["end_chapter"] == 3
    assert "不得进入近期提示词的远期秘密" not in llm.prompts[-1]


@pytest.mark.asyncio
async def test_schema_five_accepts_one_combined_chapter_plan() -> None:
    plan, llm, repository = _plan(), TacticalWorkflowLLM(), TacticalRepository()
    state = _state(plan)
    tactical = await tactical_plan_node(state, _config(llm, repository))
    state.update(tactical.update)
    generated = await chapter_outline_node(state, _config(llm, repository))
    state.update(generated.update)

    assert generated.goto == "chapter_plan_review_node"
    assert state["pending_proposal"]["kind"] == "chapter_plan"
    proposal_id = state["pending_proposal"]["proposal_id"]
    accepted = await chapter_plan_review_node(
        state, _config(llm, repository, auto=True)
    )
    outline = accepted.update["chapter_outlines"][0]
    assert accepted.goto == "router_agent"
    assert repository.accept_calls == 1
    assert repository.idempotency_keys == [proposal_id]
    assert outline["chapter_execution_contract"]["tactical_version"] == 1
    assert [beat["chapter_number"] for beat in outline["rolling_plan"]] == [1, 2, 3]


@pytest.mark.asyncio
async def test_tactical_and_outline_calls_do_not_reserve_extra_quota() -> None:
    plan, llm, repository = _plan(), TacticalWorkflowLLM(), TacticalRepository()
    quota = SimpleNamespace(reserve=AsyncMock())
    config = _config(llm, repository)
    config["configurable"]["quota_service"] = quota

    state = _state(plan)
    tactical = await tactical_plan_node(state, config)
    state.update(tactical.update)
    await chapter_outline_node(state, config)

    quota.reserve.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_five_reserves_one_chapter_quota_before_tactical_ai() -> None:
    plan, llm, repository = _plan(), TacticalWorkflowLLM(), TacticalRepository()
    quota = SimpleNamespace(reserve=AsyncMock())
    config = _config(llm, repository)
    config["configurable"].update(
        quota_service=quota,
        tenant_context=SimpleNamespace(),
    )
    state = _state(plan)
    state["workflow_run_id"] = str(uuid4())

    assert _route(state)[0] == "chapter_quota_node"
    reserved = await chapter_quota_node(state, config)
    state.update(reserved.update)

    quota.reserve.assert_awaited_once_with(
        config["configurable"]["tenant_context"],
        state["workflow_run_id"],
        "chapter",
        0,
    )
    assert _route(state)[0] == "tactical_plan_node"


@pytest.mark.parametrize("scope", ["tactical", "chapter_outline", "both"])
def test_chapter_plan_review_scope_is_validated(scope: str) -> None:
    proposal, _versions = create_proposal({}, "chapter_plan", {}, 1)
    revised = parse_review_decision({
        "proposal_id": proposal["proposal_id"],
        "decision": "revise",
        "scope": scope,
        "instruction": "加强第二场冲突",
    }, proposal)
    assert revised.scope == scope
    assert revised.instruction == "加强第二场冲突"


def test_chapter_plan_revision_scope_controls_regeneration_boundary() -> None:
    outline_only = _regenerate_chapter_plan("chapter_outline", "调整场景")
    tactical_only = _regenerate_chapter_plan("tactical", "调整战术")
    both = _regenerate_chapter_plan("both", "全部调整")
    assert outline_only.goto == "chapter_outline_node"
    assert "tactical_window" not in outline_only.update
    assert tactical_only.goto == "tactical_plan_node"
    assert tactical_only.update["chapter_outline_feedback"] is None
    assert both.update["chapter_outline_feedback"] == "全部调整"


def test_chapter_plan_rejects_unknown_revision_scope() -> None:
    proposal, _versions = create_proposal({}, "chapter_plan", {}, 1)
    with pytest.raises(InvalidReviewDecisionError, match="修改范围"):
        parse_review_decision({
            "proposal_id": proposal["proposal_id"],
            "decision": "revise",
            "scope": "raw_json",
            "instruction": "直接改 JSON",
        }, proposal)


def test_router_refreshes_tactics_after_story_revision_changes() -> None:
    plan = _plan()
    state = _state(plan)
    state["tactical_window"] = TacticalWindow.from_dict({
        "schema_version": 1,
        "version": 1,
        "novel_plan_version": 1,
        "story_state_revision": 0,
        "source": "chapter_refresh",
        "start_chapter": 1,
        "end_chapter": 3,
        "volume_id": "v1",
        "window_objective": "推进调查",
        "beats": [{
            "chapter_number": number,
            "slot_ref": f"ch{number}",
            "tactical_goal": "推进调查",
            "approach": "核验证据",
            "bridge_from_previous": "承接事实",
            "pressure_escalation": "对手反制",
            "exit_hook": "出现新目标",
            "pacing": "逐步加压",
        } for number in range(1, 4)],
    }).to_dict()
    state["chapter_quota_reserved_for_chapter"] = 0
    assert _route(state)[0] == "chapter_outline_node"
    state.update(
        current_chapter_index=1,
        memory_retrieved_for_chapter=1,
        chapter_quota_reserved_for_chapter=1,
    )
    assert _route(state)[0] == "tactical_plan_node"


@pytest.mark.asyncio
async def test_legacy_checkpoint_upgrades_at_router_after_review_clears() -> None:
    state = _state(_plan())
    state.update(
        workflow_schema_version=4,
        novel_plan=None,
        pending_proposal=None,
        current_chapter_index=2,
    )

    command = await router_agent(state, {"configurable": {
        "novel_planning_v1_enabled": True,
    }})

    assert command.goto == "novel_plan_initialize_node"
    assert command.update["workflow_schema_version"] == 5


@pytest.mark.asyncio
async def test_legacy_checkpoint_keeps_original_schema_while_review_pending() -> None:
    state = _state(_plan())
    state.update(
        workflow_schema_version=4,
        novel_plan=None,
        pending_proposal={"proposal_id": "legacy-review"},
    )

    command = await router_agent(state, {"configurable": {
        "novel_planning_v1_enabled": True,
    }})

    assert command.goto == "chapter_outline_node"
    assert "workflow_schema_version" not in command.update


def test_tactical_deviation_is_minor_but_strategy_breach_is_major() -> None:
    tactical = {"tactical_fulfillment": {"deviations": ["推进方式改变"]}}
    assert classify_drift(tactical, 4200, 4200) == "minor"
    assert classify_drift({
        **tactical, "core_arc_breached": True,
    }, 4200, 4200) == "major"
