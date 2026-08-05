"""Regression tests for cross-chapter continuity contracts and context handling."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.agents.chapter_writer_node import _build_prev_scene_digest
from application.agents.persist_node import _chapter_progress, persist_node
from application.continuity import (
    build_budgeted_context,
    build_story_bible,
    compact_story_bible,
    compact_text,
    related_character_cards,
    validate_chapter_contract,
)
from application.prompts.memory_prompts import (
    CHAPTER_SUMMARY_SCHEMA,
    build_chapter_summary_prompt,
    build_story_state_prompt,
)
from application.prompts.reflection_prompts import build_aggregation_prompt
from service.value_objects.progress import Progress


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


def test_story_bible_keeps_related_card_and_indexes_every_other_character() -> None:
    characters = [
        {"name": "许澄", "role_type": "主角", "profile": {"secret": "隐瞒旧案"}},
        {"姓名": "赵闻", "身份": "证人", "秘密": "见过凶手"},
        {"name": "周砚", "role": "调查员", "profile": {"secret": "身份存疑"}},
    ]
    total = {"story_background": "雨城", "main_characters": characters}

    bible = build_story_bible(total, max_chars=500, related_context={"characters": ["赵闻"]})

    assert "<全局规则>" in bible
    assert '"秘密": "见过凶手"' in bible
    assert "- 许澄 | 主角" in bible
    assert "- 周砚 | 调查员" in bible
    assert "隐瞒旧案" not in bible
    assert "身份存疑" not in bible


def test_story_bible_does_not_drop_middle_character_indexes_when_budget_is_small() -> None:
    characters = [
        {"姓名": f"角色{index}", "角色定位": f"身份{index}", "经历": "长" * 500}
        for index in range(8)
    ]
    bible = build_story_bible(
        {"main_characters": characters, "main_plot": {"过程": "长" * 1000}},
        max_chars=5000,
        related_context={"characters": ["角色4"]},
    )
    compacted = compact_story_bible(bible, 500)

    assert related_character_cards({"main_characters": characters}, "角色4") == [characters[4]]
    assert '"经历": "' + "长" * 500 + '"' in compacted
    for index in (0, 1, 2, 3, 5, 6, 7):
        assert f"- 角色{index} | 身份{index}" in compacted


def test_chapter_contract_requires_causal_and_rolling_plan() -> None:
    valid_contract = {
        "chapter_number": 3,
        "chapter_goal": "找到证人",
        "dramatic_question": "能否在对手前找到证人",
        "desire": "说服证人开口",
        "obstacle": "对手正在转移证人",
        "tactics": ["查档案", "赶往码头"],
        "turn": "证人主动提出交换条件",
        "price_paid": "主角暴露调查方向",
        "state_delta": "证人从躲避变为有限合作",
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
async def test_persist_node_commits_all_continuity_artifacts_together(monkeypatch) -> None:
    repository = SimpleNamespace(replace_chapter=AsyncMock())
    events: list[tuple[str, dict, str]] = []
    monkeypatch.setitem(
        persist_node.__globals__,
        "emit_workflow_event",
        lambda event_type, data, node: events.append((event_type, data, node)),
    )
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
    started_stages = [
        data["stage"] for event_type, data, _node in events
        if event_type == "status" and data.get("status") == "started"
    ]
    assert started_stages == ["chapter_summary", "story_state"]


@pytest.mark.asyncio
async def test_rewrite_preserves_existing_novel_progress() -> None:
    existing = Progress(
        current_chapter=8,
        total_chapters=12,
        percentage=66.67,
        status="writing",
        completed_words=33_600,
    )
    repository = SimpleNamespace(
        find_by_id=AsyncMock(return_value=SimpleNamespace(progress=existing))
    )

    progress = await _chapter_progress(
        repository,
        str(uuid4()),
        str(uuid4()),
        {"rewrite_chapter_id": str(uuid4())},
        {"word_count": 4200},
        3,
        25.0,
        False,
    )

    assert progress.current_chapter == 8
    assert progress.total_chapters == 12
    assert progress.completed_words == 33_600
    assert progress.status == "writing"
