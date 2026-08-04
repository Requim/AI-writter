"""设定阶段生成/审核解耦的回归测试。"""

from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.chapter_outline_node import (
    chapter_outline_node,
    chapter_outline_review_node,
)
from application.agents.creative_brief_node import (
    creative_brief_node,
    creative_brief_review_node,
)
from application.agents.metadata_persist_node import metadata_persist_node
from application.agents.outline_generator_node import (
    outline_generator_node,
    outline_review_node,
)
from application.agents.summary_generator_node import (
    summary_generator_node,
    summary_review_node,
)
from application.agents.title_generator_node import title_generator_node, title_review_node
from application.errors import InvalidReviewDecisionError, StaleWorkflowDecisionError
from application.orchestrator import NovelOrchestrator, _legacy_proposal_parts
from application.prompts.chapter_outline_prompts import CHAPTER_OUTLINE_SCHEMA
from application.prompts.creative_brief_prompts import CREATIVE_BRIEF_SCHEMA
from application.prompts.outline_prompts import OUTLINE_SCHEMA
from application.prompts.summary_prompts import SUMMARY_SCHEMA
from application.prompts.title_prompts import TITLE_CANDIDATES_SCHEMA
from application.proposals import (
    create_proposal,
    parse_review_decision,
    proposal_update,
    unpack_decision,
)
from service.entities.identity import TenantContext
from service.entities.novel import Novel


def _creative_brief() -> dict:
    return {
        "core_premise": "死者来信要求主角重查旧案",
        "protagonist_drive": "洗清父亲污名",
        "core_conflict": "真相会摧毁主角仅存的家庭",
        "theme_question": "真相是否值得一切代价",
        "reader_promise": "持续解谜并获得情感回响",
        "tone": "冷峻克制",
        "originality_anchor": "来信只在雨夜出现",
        "content_boundaries": ["不使用万能解法"],
    }


def _macro_outline() -> dict:
    return {
        "story_background": "当代城市",
        "main_characters": [{"name": name} for name in "甲乙丙丁戊己"],
        "main_plot": {"opening": "收到来信", "ending": "公开真相"},
        "writing_style": "冷峻克制",
        "total_chapters": 8,
        "volumes": [{"volume_number": 1, "start_chapter": 1, "end_chapter": 8}],
    }


def _chapter_outline() -> dict:
    return {
        "chapter_number": 1, "title": "雨夜来信", "chapter_goal": "建立悬念",
        "core_conflict": "主角收到死者来信", "key_events": ["收信", "核验笔迹"],
        "entry_state": {"time": "清晨"}, "causal_chain": ["收信", "核验", "调查"],
        "state_changes": [{"subject": "主角", "before": "不知情", "after": "调查"}],
        "knowledge_boundaries": [], "continuity_constraints": ["寄信人已死亡"],
        "exit_state": {"last_action": "拆信"}, "logic_hooks": {"setup": "旧照片"},
        "rolling_plan": [{
            "chapter_number": 1, "goal": "建立悬念", "required_event": "收到来信",
            "state_delta": "主角决定调查", "callback_ids": [], "exit_hook": "照片出现",
        }],
        "scenes": [
            {"events": {"result": "发现来信"}},
            {"events": {"result": "确认笔迹"}},
        ],
        "estimated_word_count": 3200,
    }


class _SetupLLM:
    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    async def structured_generate(self, prompt, schema, **kwargs):
        del prompt, kwargs
        values = {
            id(CREATIVE_BRIEF_SCHEMA): ("creative_brief", _creative_brief()),
            id(TITLE_CANDIDATES_SCHEMA): ("title", {"candidates": [
                {"title": "死者请于雨夜回信", "hint": "一封死者来信撕裂家庭", "total_score": 35},
                {"title": "雨停之前无人作证", "hint": "证词会随雨消失", "total_score": 32},
            ]}),
            id(SUMMARY_SCHEMA): ("summary", {
                "reader_blurb": "死者来信迫使主角重查旧案。",
                "editorial_brief": "主角追查来信，对手试图销毁证据，代价逐章升级。",
            }),
            id(OUTLINE_SCHEMA): ("outline", _macro_outline()),
            id(CHAPTER_OUTLINE_SCHEMA): ("chapter_outline", _chapter_outline()),
        }
        kind, result = values[id(schema)]
        self.calls[kind] += 1
        return result


class _OutlineWithoutWordCountLLM(_SetupLLM):
    async def structured_generate(self, prompt, schema, **kwargs):
        result = await super().structured_generate(prompt, schema, **kwargs)
        if schema is CHAPTER_OUTLINE_SCHEMA:
            result = dict(result)
            result.pop("estimated_word_count", None)
        return result


def _manual_config(llm: _SetupLLM) -> dict:
    return {"configurable": {"llm_config": {"llm_instance": llm}, "auto_mode": False}}


def _auto_config(llm: _SetupLLM) -> dict:
    return {"configurable": {"llm_config": {"llm_instance": llm}, "auto_mode": True}}


async def _assert_review_cycle(generator, reviewer, state, expected_goto: str) -> None:
    llm = _SetupLLM()
    first = await generator(state, _manual_config(llm))
    proposal = first.update["pending_proposal"]
    kind = proposal["kind"]
    review_state = {**state, **first.update, "pending_proposal_decision": {
        "proposal_id": proposal["proposal_id"], "decision": "regenerate"
    }}
    regeneration = await reviewer(review_state, _manual_config(llm))
    second = await generator({**review_state, **regeneration.update}, _manual_config(llm))
    assert llm.calls[kind] == 2
    second_proposal = second.update["pending_proposal"]
    accept_state = {**state, **second.update, "pending_proposal_decision": {
        "proposal_id": second_proposal["proposal_id"], "decision": "accept"
    }}
    accepted = await reviewer(accept_state, _manual_config(llm))
    assert accepted.goto == expected_goto
    assert llm.calls[kind] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(("generator", "reviewer", "state", "expected_goto"), [
    (creative_brief_node, creative_brief_review_node, {
        "novel_type": "suspense", "workflow_schema_version": 4,
    }, "character_design_node"),
    (title_generator_node, title_review_node, {"novel_type": "suspense", "creative_brief": _creative_brief()}, "metadata_persist_node"),
    (summary_generator_node, summary_review_node, {"novel_type": "suspense", "title": "雨夜回信", "creative_brief": _creative_brief()}, "metadata_persist_node"),
    (outline_generator_node, outline_review_node, {
        "novel_type": "suspense", "title": "雨夜回信", "summary": "读者简介",
        "editorial_summary": "规划简介", "creative_brief": _creative_brief(),
        "character_design": {"characters": _macro_outline()["main_characters"]},
    }, "persist_node"),
    (chapter_outline_node, chapter_outline_review_node, {"novel_type": "suspense", "title": "雨夜回信", "total_outline": _macro_outline(), "current_chapter_index": 0}, "router_agent"),
])
async def test_each_review_accepts_without_regeneration(
    generator, reviewer, state, expected_goto: str
) -> None:
    await _assert_review_cycle(generator, reviewer, state, expected_goto)


@pytest.mark.asyncio
@pytest.mark.parametrize(("generator", "reviewer", "state"), [
    (creative_brief_node, creative_brief_review_node, {
        "novel_type": "suspense", "workflow_schema_version": 4,
    }),
    (title_generator_node, title_review_node, {
        "novel_type": "suspense", "creative_brief": _creative_brief(),
    }),
    (summary_generator_node, summary_review_node, {
        "novel_type": "suspense", "title": "雨夜回信",
        "creative_brief": _creative_brief(),
    }),
    (outline_generator_node, outline_review_node, {
        "novel_type": "suspense", "title": "雨夜回信", "summary": "读者简介",
        "editorial_summary": "规划简介", "creative_brief": _creative_brief(),
        "character_design": {"characters": _macro_outline()["main_characters"]},
    }),
    (chapter_outline_node, chapter_outline_review_node, {
        "novel_type": "suspense", "title": "雨夜回信",
        "total_outline": _macro_outline(), "current_chapter_index": 0,
    }),
])
async def test_auto_mode_also_crosses_checkpointed_review_node(
    generator, reviewer, state,
) -> None:
    llm = _SetupLLM()
    generated = await generator(state, _auto_config(llm))
    proposal = generated.update["pending_proposal"]
    calls = llm.calls[proposal["kind"]]
    accepted = await reviewer({**state, **generated.update}, _auto_config(llm))
    assert generated.goto.endswith("_review_node")
    assert accepted.goto != generated.goto
    assert llm.calls[proposal["kind"]] == calls == 1


class _SummarySequenceLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    async def structured_generate(self, prompt, schema, **_kwargs):
        assert schema is SUMMARY_SCHEMA
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]


@pytest.mark.asyncio
async def test_summary_retries_once_then_auto_accepts_valid_dual_view() -> None:
    llm = _SummarySequenceLLM([
        {"reader_blurb": "相同 简介", "editorial_brief": "相同\n简介"},
        {"reader_blurb": "面向读者的悬念", "editorial_brief": "面向规划的冲突升级"},
    ])
    state = {
        "novel_type": "suspense", "title": "雨夜回信",
        "summary_feedback": "保留冷峻语气",
    }
    generated = await summary_generator_node(state, _auto_config(llm))
    accepted = await summary_review_node({**state, **generated.update}, _auto_config(llm))
    assert len(llm.prompts) == 2 and "不得相同" in llm.prompts[1]
    assert "保留冷峻语气" in llm.prompts[1]
    assert generated.update["pending_proposal"]["payload"].get("human_review_required") is None
    assert accepted.goto == "metadata_persist_node"


@pytest.mark.asyncio
async def test_invalid_dual_summary_forces_human_review_in_auto_mode(monkeypatch) -> None:
    llm = _SummarySequenceLLM([
        {"reader_blurb": "", "editorial_brief": ""},
        {"reader_blurb": "仍然相同", "editorial_brief": "仍然相同"},
    ])
    state = {"novel_type": "suspense", "title": "雨夜回信"}
    generated = await summary_generator_node(state, _auto_config(llm))
    proposal = generated.update["pending_proposal"]
    captured: dict = {}

    def fake_interrupt(payload):
        captured.update(payload)
        return {"proposal_id": proposal["proposal_id"], "decision": "regenerate"}

    monkeypatch.setattr("application.proposals.interrupt", fake_interrupt)
    reviewed = await summary_review_node({**state, **generated.update}, _auto_config(llm))
    assert proposal["payload"]["human_review_required"] is True
    assert proposal["payload"]["validation_errors"]
    assert captured["action"] == "summary_review_required"
    assert reviewed.goto == "summary_node" and len(llm.prompts) == 2


@pytest.mark.asyncio
async def test_current_summary_rejects_single_string_replacement() -> None:
    update = proposal_update(
        {"workflow_schema_version": 4}, "summary",
        {"reader_blurb": "读者简介", "editorial_brief": "编辑简介"},
    )
    proposal = update["pending_proposal"]
    state = {
        **update, "workflow_schema_version": 4,
        "pending_proposal_decision": {
            "proposal_id": proposal["proposal_id"], "decision": "replace",
            "value": "单视图简介",
        },
    }
    with pytest.raises(InvalidReviewDecisionError, match="简介提案无效"):
        await summary_review_node(state, {"configurable": {}})


@pytest.mark.parametrize("version", [2, 3, 4])
def test_proposal_update_preserves_checkpoint_schema(version: int) -> None:
    update = proposal_update({"workflow_schema_version": version}, "title", [])
    assert update["workflow_schema_version"] == version


@pytest.mark.asyncio
async def test_title_review_can_select_a_non_first_candidate() -> None:
    llm = _SetupLLM()
    state = {"novel_type": "suspense", "creative_brief": _creative_brief()}
    generated = await title_generator_node(state, _manual_config(llm))
    proposal = generated.update["pending_proposal"]
    selected = proposal["payload"][1]
    review_state = {**state, **generated.update, "pending_proposal_decision": {
        "proposal_id": proposal["proposal_id"], "decision": "modify", "value": selected
    }}
    command = await title_review_node(review_state, _manual_config(llm))
    assert command.update["title"] == selected["title"]
    assert llm.calls["title"] == 1


@pytest.mark.asyncio
async def test_chapter_outline_defaults_to_five_thousand_words() -> None:
    llm = _OutlineWithoutWordCountLLM()
    state = {
        "novel_type": "suspense", "title": "雨夜回信",
        "total_outline": _macro_outline(), "current_chapter_index": 0,
    }

    generated = await chapter_outline_node(state, _manual_config(llm))

    assert generated.update["pending_proposal"]["payload"]["estimated_word_count"] == 5000


def test_stale_proposal_decision_is_rejected() -> None:
    proposal, _ = create_proposal({}, "title", [{"title": "有效书名"}])
    with pytest.raises(StaleWorkflowDecisionError, match="提案已更新"):
        unpack_decision(
            {"proposal_id": "outdated", "decision": "accept"}, proposal
        )

    with pytest.raises(StaleWorkflowDecisionError):
        unpack_decision({"decision": "accept"}, proposal)


def test_modify_text_is_feedback_but_mapping_is_replacement() -> None:
    proposal, _ = create_proposal({}, "outline", _macro_outline())
    base = {"proposal_id": proposal["proposal_id"], "decision": "modify"}

    feedback = parse_review_decision({**base, "value": "加强反派反制"}, proposal)
    replacement = parse_review_decision({**base, "value": _macro_outline()}, proposal)

    assert feedback.action == "revise"
    assert feedback.instruction == "加强反派反制"
    assert replacement.action == "replace"
    assert replacement.value == _macro_outline()


def test_review_decision_matches_frontend_instruction_contract() -> None:
    proposal, _ = create_proposal({}, "outline", _macro_outline())
    proposal_id = proposal["proposal_id"]

    revision = parse_review_decision({
        "proposal_id": proposal_id,
        "decision": "revise",
        "instruction": "加强第二幕因果链",
    }, proposal)
    regeneration = parse_review_decision({
        "proposal_id": proposal_id,
        "decision": "regenerate",
        "feedback": "换成更克制的方案",
    }, proposal)

    assert (revision.action, revision.instruction) == (
        "revise", "加强第二幕因果链"
    )
    assert (regeneration.action, regeneration.feedback) == (
        "regenerate", "换成更克制的方案"
    )


def test_revise_requires_instruction() -> None:
    proposal, _ = create_proposal({}, "outline", _macro_outline())
    raw = {"proposal_id": proposal["proposal_id"], "decision": "revise"}

    with pytest.raises(InvalidReviewDecisionError, match="instruction"):
        parse_review_decision(raw, proposal)


def test_replace_rejects_incomplete_outline_value() -> None:
    proposal, _ = create_proposal({}, "outline", _macro_outline())
    raw = {
        "proposal_id": proposal["proposal_id"],
        "decision": "replace",
        "value": "只是一条修改意见",
    }

    with pytest.raises(InvalidReviewDecisionError, match="完整值"):
        parse_review_decision(raw, proposal)


@pytest.mark.asyncio
async def test_outline_text_modification_returns_to_generator() -> None:
    proposal, versions = create_proposal({}, "outline", _macro_outline())
    state = {
        "workflow_schema_version": 4,
        "proposal_versions": versions,
        "pending_proposal": proposal,
        "pending_proposal_decision": {
            "proposal_id": proposal["proposal_id"],
            "decision": "modify",
            "value": "增强中段因果和对手反制",
        },
    }

    command = await outline_review_node(state, {})

    assert command.goto == "outline_node"
    assert command.update["outline_feedback"] == "增强中段因果和对手反制"
    assert command.update["pending_proposal"] is None


@pytest.mark.asyncio
async def test_outline_regenerate_keeps_feedback_and_action_semantics() -> None:
    proposal, versions = create_proposal({}, "outline", _macro_outline())
    state = {
        "workflow_schema_version": 4,
        "proposal_versions": versions,
        "pending_proposal": proposal,
        "pending_proposal_decision": {
            "proposal_id": proposal["proposal_id"],
            "decision": "regenerate",
            "feedback": "重做一版但保留核心谜面",
        },
    }

    command = await outline_review_node(state, {})

    assert command.goto == "outline_node"
    assert command.update["outline_feedback"] == "重做一版但保留核心谜面"


@pytest.mark.asyncio
async def test_metadata_node_persists_title_and_summary_immediately() -> None:
    novel = Novel(title="旧书名", summary="旧简介")
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=novel), update=AsyncMock(return_value=novel)
    )
    config = {"configurable": {
        "novel_repository": repository, "tenant_id": "tenant", "novel_id": str(novel.id)
    }}
    command = await metadata_persist_node(
        {"title": "新书名", "summary": "新简介", "__next_node__": "outline_node"}, config
    )
    assert command.goto == "outline_node"
    assert novel.title == "新书名" and novel.summary == "新简介"
    repository.update.assert_awaited_once()


def test_legacy_summary_interrupt_is_rebuilt_as_structured_proposal() -> None:
    parts = _legacy_proposal_parts({
        "action": "confirm_or_provide_summary", "ai_generated_summary": "旧版简介"
    })
    assert parts == (
        "summary",
        {
            "reader_blurb": "旧版简介", "editorial_brief": "旧版简介",
            "legacy_single_view": True,
        },
        None,
    )


def test_legacy_quality_interrupt_reuses_review_result() -> None:
    parts = _legacy_proposal_parts({
        "action": "review_reflection_issues",
        "chapter_number": 2,
        "quality_score": 0.76,
        "rubric_scores": {"causality": 3.8},
        "word_count_analysis": {"effective_density": 78},
        "issues": [{"issue_id": "logic-1"}],
    })

    assert parts is not None
    kind, payload, chapter = parts
    assert (kind, chapter) == ("reflection", 2)
    assert payload["gate"]["score"] == 0.76
    assert payload["issues"][0]["issue_id"] == "logic-1"


@pytest.mark.asyncio
async def test_orchestrator_injects_legacy_proposal_before_resume() -> None:
    interrupt = SimpleNamespace(value={
        "action": "confirm_or_provide_title",
        "ai_suggestions": [{"title": "雨夜回信"}],
    })
    snapshot = SimpleNamespace(values={}, tasks=[SimpleNamespace(interrupts=[interrupt])])
    orchestrator = NovelOrchestrator(SimpleNamespace(), SimpleNamespace(), {})
    orchestrator._workflow = SimpleNamespace(aget_state=AsyncMock(return_value=snapshot))
    context = TenantContext(
        tenant_id="tenant", tenant_name="租户", user_id="user", role="owner",
        is_platform_admin=False, ai_enabled=True, monthly_generation_limit=30,
    )
    command = await orchestrator.prepare_resume_command(context, "thread", "accept")
    assert command.update["pending_proposal"]["kind"] == "title"
    assert command.update["pending_proposal_decision"] == "accept"


@pytest.mark.asyncio
async def test_legacy_revision_preview_is_recomputed_only_once() -> None:
    interrupt = SimpleNamespace(value={
        "action": "confirm_revision", "revised_content_preview": "旧版预览",
    })
    first = SimpleNamespace(
        values={}, tasks=[SimpleNamespace(interrupts=[interrupt])],
    )
    second = SimpleNamespace(
        values={"legacy_revision_recompute_done": True},
        tasks=[SimpleNamespace(interrupts=[interrupt])],
    )
    workflow = SimpleNamespace(
        aget_state=AsyncMock(side_effect=[first, second]),
        aupdate_state=AsyncMock(),
    )
    orchestrator = NovelOrchestrator(SimpleNamespace(), SimpleNamespace(), {})
    orchestrator._workflow = workflow
    context = TenantContext(
        tenant_id="tenant", tenant_name="租户", user_id="user", role="owner",
        is_platform_admin=False, ai_enabled=True, monthly_generation_limit=30,
    )
    command = await orchestrator.prepare_resume_command(context, "thread", "accept")
    assert command is None
    update = workflow.aupdate_state.await_args.args[1]
    assert update["next_tool"] == "revision_node"
    assert update["legacy_revision_recompute_done"] is True
    with pytest.raises(StaleWorkflowDecisionError, match="已重算"):
        await orchestrator.prepare_resume_command(context, "thread", "accept")
