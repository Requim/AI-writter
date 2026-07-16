"""Regression tests for cross-chapter continuity contracts and context handling."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.agents.chapter_writer_node import _build_prev_scene_digest
from application.agents.persist_node import persist_node
from application.continuity import (
    build_budgeted_context,
    compact_text,
    validate_chapter_contract,
)
from application.prompts.memory_prompts import (
    CHAPTER_SUMMARY_SCHEMA,
    build_chapter_summary_prompt,
    build_story_state_prompt,
)
from application.prompts.reflection_prompts import build_aggregation_prompt


def test_compact_text_preserves_ending() -> None:
    text = "开" * 1000 + "关键结尾"
    compacted = compact_text(text, 200)
    assert compacted.startswith("开")
    assert compacted.endswith("关键结尾")
    assert "中间内容按预算压缩" in compacted


def test_budgeted_context_preserves_every_memory_layer() -> None:
    context = "\n\n".join(
        [
            "<S层故事状态>\n" + "状态" * 800,
            "<P层滚动规划>\n" + "规划" * 800,
            "<M层近期章节>\n" + "近期" * 800,
            "<L层历史章节摘录>\n" + "历史" * 800,
        ]
    )
    result = build_budgeted_context(context, max_chars=1200)
    assert "<S层故事状态>" in result
    assert "<P层滚动规划>" in result
    assert "<M层近期章节>" in result
    assert "<L层历史章节摘录>" in result


def test_chapter_contract_requires_causal_and_rolling_plan() -> None:
    valid_contract = {
        "chapter_number": 3,
        "chapter_goal": "找到证人",
        "key_events": ["发现地址", "见到证人"],
        "scenes": [{}, {}, {}],
        "entry_state": {"location": "警局"},
        "exit_state": {"location": "码头"},
        "causal_chain": ["查档案", "发现地址", "赶往码头"],
        "rolling_plan": [{"chapter_number": 3}],
    }
    assert validate_chapter_contract(valid_contract, 3) == []

    invalid = dict(valid_contract, causal_chain=[], rolling_plan=[])
    issues = validate_chapter_contract(invalid, 3)
    assert "causal_chain 少于 2 步" in issues
    assert "rolling_plan 未覆盖当前章节" in issues


def test_memory_prompts_include_previous_state_and_chapter_ending() -> None:
    content = "章节开头" + "过程" * 5000 + "结尾主角失去钥匙"
    summary_prompt = build_chapter_summary_prompt("测试章", content)
    state_prompt = build_story_state_prompt(
        2,
        "测试章",
        content,
        previous_state='{"immutable_facts":[{"fact":"钥匙原本在主角手中"}]}',
        chapter_outline={"exit_state": {"inventory": []}},
    )
    assert "结尾主角失去钥匙" in summary_prompt
    assert "钥匙原本在主角手中" in state_prompt
    assert "结尾主角失去钥匙" in state_prompt


def test_global_review_receives_complete_chapter_boundaries() -> None:
    content = "第一幕事实" + "中段" * 3000 + "终幕事实"
    prompt = build_aggregation_prompt(
        chunk_results=[],
        chapter_content=content,
        chapter_outline={"chapter_goal": "推进调查"},
        main_characters=[],
        memory_context="<S层故事状态>\n主角受伤",
        content_length=len(content),
    )
    assert "第一幕事实" in prompt
    assert "终幕事实" in prompt
    assert "主角受伤" in prompt


def test_scene_digest_uses_actual_generated_ending() -> None:
    content = "过程" * 500 + "她把唯一的钥匙扔进河里"
    digest = _build_prev_scene_digest(
        {"events": {"struggle": "是否毁掉证据", "result": "证据消失"}},
        content,
    )
    assert "证据消失" in digest
    assert "她把唯一的钥匙扔进河里" in digest


@pytest.mark.asyncio
async def test_persist_node_commits_all_continuity_artifacts_together() -> None:
    repository = SimpleNamespace(replace_chapter=AsyncMock())
    memory_service = SimpleNamespace(
        build_chapter_memory=lambda chapter: (
            "章节头尾记忆",
            {"type": "chapter", "chapter_index": chapter["chapter_index"]},
        )
    )
    async def generate_structured(*_args, schema, **_kwargs):
        if schema is CHAPTER_SUMMARY_SCHEMA:
            return {"summary": "章节摘要，包含最终动作。"}
        return {
                "timeline": {"current_time": "午夜"},
                "locations": [],
                "characters": [],
                "open_conflicts": [],
                "foreshadowing": [],
                "revealed_secrets": [],
                "unrevealed_secrets": [],
                "immutable_facts": [{"fact": "钥匙已沉入河底"}],
                "last_transition": {"last_action": "离开河岸"},
                "updated_through_chapter": 1,
            }

    llm = SimpleNamespace(
        structured_generate=AsyncMock(side_effect=generate_structured),
    )
    rolling_plan = [{"chapter_number": 1}, {"chapter_number": 2}]
    state = {
        "current_chapter_index": 0,
        "current_chapter_content": "正文" * 1600,
        "chapter_outlines": [
            {
                "title": "钥匙",
                "rolling_plan": rolling_plan,
                "exit_state": {"last_action": "离开河岸"},
            }
        ],
        "total_outline": {"total_chapters": 10},
        "memory_context": (
            '<S层故事状态>\n{"immutable_facts":[{"fact":"钥匙原本在主角手中"}]}'
        ),
    }
    await persist_node(
        state,  # type: ignore[arg-type]
        {
            "configurable": {
                "novel_repository": repository,
                "memory_service": memory_service,
                "novel_id": str(uuid4()),
                "tenant_id": str(uuid4()),
                "llm_config": {"llm_instance": llm},
            }
        },  # type: ignore[arg-type]
    )

    kwargs = repository.replace_chapter.await_args.kwargs
    assert kwargs["chapter_summary"] == "章节摘要，包含最终动作。"
    assert json.loads(kwargs["story_state"])["updated_through_chapter"] == 1
    assert json.loads(kwargs["rolling_plan"]) == rolling_plan
