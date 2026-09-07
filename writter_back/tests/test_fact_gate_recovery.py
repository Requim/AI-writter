"""真实 LangGraph 检查点恢复不能绕过人工事实复核。"""
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from application.fact_gate_workflow import check_fact_artifact, fact_review_node
from application.errors import InvalidReviewDecisionError, StaleWorkflowDecisionError
from application.schemas.agent_state import NovelAgentState
from tests.test_fact_gate import setup_gate, config


async def start_check(state: NovelAgentState, config: RunnableConfig) -> Command:
    return await check_fact_artifact(state, config, state["current_chapter_content"], "body", Command(goto="done", update={"title": "已继续"}))


def graph():
    builder = StateGraph(NovelAgentState)
    builder.add_node("check", start_check)
    builder.add_node("fact_review_node", fact_review_node)
    builder.add_node("done", lambda state: {})
    builder.add_edge(START, "check")
    builder.add_edge("done", END)
    return builder.compile(checkpointer=InMemorySaver())


@pytest.mark.asyncio
async def test_automatic_mode_interrupts_and_bound_ack_resumes_checkpoint():
    cfg = config(setup_gate())
    cfg["configurable"].update(thread_id="fact-recovery", auto_mode=True)
    app = graph()
    result = await app.ainvoke({"current_chapter_content": "他推开门。", "current_chapter_index": 0}, cfg)
    interrupt = result["__interrupt__"][0].value
    assert interrupt["action"] == "fact_review_required"
    assert interrupt["artifact_content"] == "他推开门。"
    assert "title" not in result
    result = await app.ainvoke(Command(resume={"proposal_id": interrupt["proposal_id"], "decision": "accept"}), cfg)
    assert result["title"] == "已继续"
    assert result["fact_reports"]["body"]["status"] == "unknown"
    assert result["fact_acknowledgements"]["body"]["reviewed_by"]


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["accept", "replace"])
async def test_hard_conflict_cannot_be_accepted_or_replaced(decision):
    cfg = config(setup_gate())
    cfg["configurable"]["thread_id"] = "hard-" + decision
    app = graph()
    result = await app.ainvoke({"current_chapter_content": "辛家祖祠归陆家所有。"}, cfg)
    proposal = result["__interrupt__"][0].value["proposal_id"]
    with pytest.raises(InvalidReviewDecisionError):
        await app.ainvoke(Command(resume={"proposal_id": proposal, "decision": decision, "value": "强行接受"}), cfg)
    assert "title" not in (await app.aget_state(cfg)).values


@pytest.mark.asyncio
async def test_old_confirmation_after_fact_change_creates_new_proposal():
    value = setup_gate()
    cfg = config(value)
    cfg["configurable"]["thread_id"] = "changed"
    app = graph()
    result = await app.ainvoke({"current_chapter_content": "他推开门。"}, cfg)
    proposal = result["__interrupt__"][0].value["proposal_id"]
    cfg["configurable"]["story_fact_repository"].capture_constraints.return_value = value.model_copy(update={"fact_heads": ()})
    result = await app.ainvoke(Command(resume={"proposal_id": proposal, "decision": "accept"}), cfg)
    assert result["__interrupt__"][0].value["proposal_id"] != proposal
    assert "title" not in result


@pytest.mark.asyncio
async def test_wrong_proposal_and_edited_body_cannot_resume_old_confirmation():
    cfg = config(setup_gate())
    cfg["configurable"]["thread_id"] = "stale"
    app = graph()
    result = await app.ainvoke({"current_chapter_content": "他推开门。"}, cfg)
    proposal = result["__interrupt__"][0].value["proposal_id"]
    with pytest.raises(StaleWorkflowDecisionError):
        await app.ainvoke(Command(resume={"proposal_id": "old", "decision": "accept"}), cfg)
    saved = (await app.aget_state(cfg)).values
    with pytest.raises(StaleWorkflowDecisionError):
        await fact_review_node({**saved, "current_chapter_content": "已经修改",
            "pending_proposal_decision": {"proposal_id": proposal, "decision": "accept"}}, cfg)


@pytest.mark.asyncio
async def test_complete_legacy_workflow_keeps_fact_reviews_separate_from_auto_quality_accept():
    from application.workflow_builder import create_novel_workflow
    from tests.test_workflow_flow import FakeWorkflowLLM, _manual_workflow_input
    cfg = config(setup_gate(), FakeWorkflowLLM())
    cfg["recursion_limit"] = 120
    cfg["configurable"].update(thread_id="complete-fact-workflow", auto_mode=True)
    app = create_novel_workflow(InMemorySaver())
    result = await app.ainvoke(_manual_workflow_input(), cfg)
    kinds = []
    for _ in range(8):
        if result.get("is_completed"):
            break
        interrupt = result["__interrupt__"][0].value
        assert interrupt["action"] == "fact_review_required"
        kinds.append(interrupt["fact_report"]["artifact_kind"])
        result = await app.ainvoke(Command(resume={"proposal_id": interrupt["proposal_id"], "decision": "accept"}), cfg)
    assert result["is_completed"]
    assert "outline" in kinds and "body" in kinds
    decision = result["last_persisted_chapter"]["user_decision"]
    assert decision["fact_gate"]["status"] == "unknown"
    assert decision["fact_review"]["reviewed_by"]


@pytest.mark.asyncio
async def test_corrected_ledger_can_recheck_same_draft_without_regeneration():
    from tests.test_fact_gate import judge
    value = setup_gate()
    content = "辛家祖祠归陆家所有。"
    llm = judge(value, "辛家祖祠归陆家所有")
    llm.structured_generate.return_value["claims"][0]["object_entity_id"] = str(value.entities[-1].id)
    cfg = config(value, llm)
    cfg["configurable"]["thread_id"] = "correct-and-recheck"
    app = graph()
    result = await app.ainvoke({"current_chapter_content": content}, cfg)
    proposal = result["__interrupt__"][0].value["proposal_id"]
    corrected = value.fact_heads[0].model_copy(update={"version": 2, "object_entity_id": value.entities[-1].id})
    cfg["configurable"]["story_fact_repository"].capture_constraints.return_value = value.model_copy(update={"fact_heads": (corrected,)})
    result = await app.ainvoke(Command(resume={"proposal_id": proposal, "decision": "recheck"}), cfg)
    assert result["title"] == "已继续"
    assert result["current_chapter_content"] == content
    assert result["fact_reports"]["body"]["status"] == "pass"
