"""Regression tests for the premise, dramatic-contract and quality pipeline."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from api.routers.workflow_router import _seed_initial_input
from application.agents.chapter_writer_node import _build_scene_ledger_entry
from application.agents.reflection_node import _quality_gate, reflection_node
from application.agents.revision_node import apply_structured_patch, revision_node
from application.agents.title_generator_node import _normalize_candidates
from application.errors import QualityGateReviewRequired, RetryableWorkflowError
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.prompts.chapter_writer_prompts import build_next_scene_prompt
from application.prompts.creative_brief_prompts import (
    build_creative_brief_prompt,
    build_legacy_creative_brief,
    validate_creative_brief,
)
from application.prompts.title_prompts import build_title_prompt
from application.prompts.version import PROMPT_VERSION
from application.workflow_builder import create_novel_workflow
from service.entities.novel import Novel
from service.value_objects.outline import Outline


def _rubric(score: float) -> dict[str, float]:
    return {
        "causality": score,
        "continuity": score,
        "character": score,
        "scene_function": score,
        "voice": score,
        "prose_specificity": score,
        "ending_effect": score,
    }


def _review_result(score: float, issues: list[dict] | None = None) -> dict:
    return {
        "passed": False,
        "rubric_scores": _rubric(score),
        "hard_failures": [],
        "word_count_analysis": {
            "total_count": 3600,
            "effective_density": 85,
            "is_valid_word_count": True,
        },
        "issues": issues or [],
    }


class _CreativeBriefLLM:
    def __init__(self) -> None:
        self.brief_calls = 0

    async def structured_generate(self, prompt, schema, **kwargs):
        if "core_premise" in schema:
            self.brief_calls += 1
            return {
                "core_premise": "死者来信要求主角重查旧案",
                "protagonist_drive": "洗清父亲污名",
                "core_conflict": "查明真相会摧毁主角仅存的家庭关系",
                "theme_question": "真相是否值得一切代价",
                "reader_promise": "持续解谜并获得情感回响",
                "tone": "冷峻克制",
                "originality_anchor": "来信只在雨夜出现",
                "content_boundaries": ["不使用无依据的超自然解答"],
            }
        return {"candidates": [{"title": "死者请于雨夜回信", "total_score": 35}]}


class _LowScoreReviewLLM:
    async def structured_generate(self, prompt, schema, **kwargs):
        return _review_result(3.0)


class _PatchFallbackLLM:
    async def structured_generate(self, prompt, schema, **kwargs):
        return {"edits": [], "unresolved_issue_ids": ["pacing-1"]}

    async def stream_text(self, prompt, **kwargs):
        yield "重构后的章节保留原有事实，并补足了完整因果和场景转折。"


def test_creative_brief_is_versioned_and_legacy_outline_can_be_backfilled() -> None:
    brief = build_legacy_creative_brief(
        "suspense",
        "回声来信",
        "死者寄来一封要求主角查明旧案的信",
        {"main_plot": {"起": "收到信"}, "story_background": "当代城市", "writing_style": "冷峻"},
    )

    assert validate_creative_brief(brief) == []
    assert f"PROMPT_VERSION:{PROMPT_VERSION}" in build_creative_brief_prompt("suspense")
    assert f"PROMPT_VERSION:{PROMPT_VERSION}" in build_title_prompt("suspense", brief)


def test_persisted_creative_brief_is_seeded_into_a_new_workflow() -> None:
    novel = Novel(
        novel_type="suspense",
        total_outline=Outline(
            total_chapters=12,
            creative_brief={"core_premise": "死者来信迫使主角重查旧案"},
            prompt_version=PROMPT_VERSION,
        ),
    )
    input_data: dict[str, object] = {}

    _seed_initial_input(input_data, novel)

    assert input_data["creative_brief"] == novel.total_outline.creative_brief
    assert input_data["prompt_version"] == PROMPT_VERSION


def test_title_candidates_are_selected_by_score_instead_of_output_order() -> None:
    candidates = _normalize_candidates(
        {
            "candidates": [
                {"title": "排在前面的名字", "total_score": 18},
                {"title": "死者请于雨夜回信", "total_score": 35},
            ]
        }
    )

    assert candidates[0]["title"] == "死者请于雨夜回信"


def test_chapter_contract_prompt_is_reproducible_and_allows_adaptive_scenes() -> None:
    kwargs = {
        "chapter_index": 4,
        "novel_type": "suspense",
        "title": "回声来信",
        "total_outline": {"total_chapters": 12, "volumes": []},
        "memory_context": "上一章发现寄信人已经死亡",
    }

    first = build_chapter_outline_prompt(**kwargs)
    second = build_chapter_outline_prompt(**kwargs)

    assert first == second
    assert "2-5 个场景" in first
    assert "desire" in first and "price_paid" in first and "state_delta" in first


def test_scene_ledger_keeps_planned_delta_and_actual_generated_ending() -> None:
    content = "主角试图说服证人。\n\n证人最终把钥匙扔进河里。"
    ledger = _build_scene_ledger_entry(
        1,
        {"turn": "证人拒绝", "price_paid": "失去钥匙", "state_delta": "线索中断"},
        content,
    )
    prompt = build_next_scene_prompt(
        scene={}, chapter_outline={}, novel_type="suspense", title="回声来信",
        chapter_num=1, ch_title="雨夜", scene_index=2, total_scenes=3,
        prev_scene_digest="证人拒绝合作", prev_word_count=1000, correction_note="",
        target_words=1500, logic_hooks={}, internal_monologue="", memory_context="",
        scene_ledger=[ledger],
    )

    assert ledger["planned_state_delta"] == "线索中断"
    assert "证人最终把钥匙扔进河里" in ledger["actual_ending"]
    assert "已完成场景账本" in prompt and "线索中断" in prompt


def test_server_quality_gate_ignores_model_passed_and_uses_rubric() -> None:
    good_gate, _ = _quality_gate(_review_result(4.2), "正文" * 1800)
    low_gate, _ = _quality_gate(_review_result(3.0), "正文" * 1800)

    assert good_gate["decision"] == "pass"
    assert low_gate["decision"] == "human_review"


@pytest.mark.parametrize(("raw_score", "expected_score"), [(8.4, 0.84), (84, 0.84)])
def test_server_quality_gate_normalizes_model_rubric_scale(
    raw_score: float, expected_score: float
) -> None:
    result = _review_result(4.2)
    result["rubric_scores"] = _rubric(raw_score)

    gate, _ = _quality_gate(result, "正文" * 1800)

    assert gate["score"] == pytest.approx(expected_score)
    assert gate["decision"] == "pass"


def test_evidenced_hard_failure_routes_to_refactor() -> None:
    content = "主角明知门后有埋伏，却毫无理由地独自走了进去。" + "正文" * 1800
    issue = {
        "issue_id": "logic-1",
        "type": "logic",
        "severity": "high",
        "priority_action": "must_fix",
        "issue_resolved": False,
        "evidence": "主角明知门后有埋伏，却毫无理由地独自走了进去。",
    }
    result = _review_result(4.2, [issue])
    result["hard_failures"] = ["logic-1"]

    gate, issues = _quality_gate(result, content)

    assert gate["decision"] == "refactor"
    assert issues[0]["evidence_valid"] is True


def test_quality_gate_normalizes_malformed_issue_enums() -> None:
    content = "证人把钥匙放回桌面。" + "正文" * 1800
    result = _review_result(4.2, [{
        "type": ["logic"],
        "severity": "high",
        "priority_action": ["must_fix"],
        "evidence": "证人把钥匙放回桌面。",
    }])
    result["hard_failures"] = {"issue_id": "invalid-shape"}

    gate, issues = _quality_gate(result, content)

    assert gate["decision"] == "patch"
    assert issues[0]["type"] == "unknown"
    assert issues[0]["priority_action"] == "must_fix"


def test_structured_patch_applies_only_unique_allowed_anchors() -> None:
    content = "雨落在窗上。证人把唯一的钥匙放回桌面。主角没有伸手。"
    payload = {
        "edits": [{
            "issue_id": "pacing-1",
            "anchor": "证人把唯一的钥匙放回桌面。",
            "replacement": "证人捏着钥匙停了片刻，随后把它推回桌面。",
        }],
        "unresolved_issue_ids": [],
    }

    revised = apply_structured_patch(content, payload, {"pacing-1"})

    assert revised == "雨落在窗上。证人捏着钥匙停了片刻，随后把它推回桌面。主角没有伸手。"


def test_structured_patch_rejects_ambiguous_anchor_atomically() -> None:
    content = "同一句话反复出现。同一句话反复出现。结尾不变。"
    payload = {
        "edits": [{
            "issue_id": "padding-1",
            "anchor": "同一句话反复出现。",
            "replacement": "只保留一次。",
        }],
        "unresolved_issue_ids": [],
    }

    with pytest.raises(RetryableWorkflowError, match="锚点不唯一"):
        apply_structured_patch(content, payload, {"padding-1"})


def test_structured_patch_rejects_more_than_safe_edit_limit() -> None:
    content = "正文内容足够长，可以进行局部替换。"
    payload = {
        "edits": [
            {"issue_id": "pacing-1", "anchor": "正文内容足够长", "replacement": "正文内容依然足够长"}
            for _ in range(13)
        ],
        "unresolved_issue_ids": [],
    }

    with pytest.raises(RetryableWorkflowError, match="超过安全上限"):
        apply_structured_patch(content, payload, {"pacing-1"})


@pytest.mark.asyncio
async def test_creative_brief_regeneration_stays_on_single_graph_branch() -> None:
    llm = _CreativeBriefLLM()
    workflow = create_novel_workflow(InMemorySaver())
    config = {
        "configurable": {
            "thread_id": "creative-brief-regeneration",
            "llm_config": {"llm_instance": llm},
            "auto_mode": False,
        }
    }
    first = await workflow.ainvoke({"novel_type": "suspense"}, config)
    assert first["__interrupt__"][0].value["action"] == "review_or_modify_creative_brief"

    second = await workflow.ainvoke(Command(resume="regenerate"), config)

    actions = [item.value["action"] for item in second["__interrupt__"]]
    assert actions == ["review_or_modify_creative_brief"]
    # 恢复 interrupt 会重放当前节点一次，随后 regenerate 再进入一次本节点。
    assert llm.brief_calls == 3


@pytest.mark.asyncio
async def test_direct_rewrite_never_interrupts_outside_graph_context() -> None:
    state = {
        "current_chapter_content": "正文" * 1800,
        "chapter_outlines": [{}],
        "total_outline": {},
        "revision_attempts": 0,
    }
    config = {
        "configurable": {
            "llm_config": {"llm_instance": _LowScoreReviewLLM()},
            "auto_mode": True,
            "direct_rewrite": True,
            "max_reflection_loops": 1,
        }
    }

    command = await reflection_node(state, config)
    assert command.goto == "revision_node"
    assert command.update["quality_gate"]["decision"] == "refactor"

    state["revision_attempts"] = 1
    with pytest.raises(QualityGateReviewRequired, match="质量门禁"):
        await reflection_node(state, config)


@pytest.mark.asyncio
async def test_patch_failure_falls_back_to_full_refactor() -> None:
    state = {
        "current_chapter_content": "原章节内容保持基本事实。",
        "current_chapter_index": 0,
        "chapter_outlines": [{}],
        "total_outline": {},
        "memory_context": "",
        "quality_gate": {"decision": "patch"},
        "reflection_issues": [{
            "issue_id": "pacing-1",
            "priority_action": "must_fix",
            "evidence_valid": True,
        }],
        "revision_attempts": 0,
    }
    config = {
        "configurable": {
            "llm_config": {"llm_instance": _PatchFallbackLLM()},
            "auto_mode": True,
        }
    }

    command = await revision_node(state, config)

    assert command.goto == "reflection_node"
    assert command.update["current_chapter_content"].startswith("重构后的章节")
