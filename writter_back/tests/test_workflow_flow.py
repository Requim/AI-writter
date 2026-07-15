"""Tests for the deterministic macro-outline and per-chapter workflow."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from api.routers.workflow_router import (
    WorkflowInvokeRequest,
    _prepare_request,
    _public_error_data,
)
from application.agents.router_agent import _route
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.prompts.outline_prompts import build_outline_prompt, validate_outline
from service.entities.identity import TenantContext


def test_macro_outline_prompt_does_not_request_all_chapters():
    prompt = build_outline_prompt("suspense", "测试书名", "测试简介")
    assert '"chapters": [' not in prompt
    assert '"total_chapters": 180' not in prompt
    assert "禁止输出 chapters 字段" in prompt


def test_macro_outline_validation_accepts_volume_only_contract():
    outline = {
        "story_background": "有限制的世界",
        "main_characters": [{"姓名": str(index)} for index in range(6)],
        "main_plot": {"起": "开始", "承": "发展", "转": "反转", "合": "结束"},
        "writing_style": "第三人称有限视角",
        "total_chapters": 120,
        "volumes": [{"start_chapter": 1, "end_chapter": 120}],
    }
    assert validate_outline(outline)["valid"] is True


def test_chapter_outline_prompt_uses_current_volume_and_macro_context():
    prompt = build_chapter_outline_prompt(
        chapter_index=31,
        novel_type="suspense",
        title="测试书名",
        total_outline={
            "story_background": "世界规则",
            "main_characters": [{"姓名": "林舟"}],
            "main_plot": {"承": "调查升级"},
            "writing_style": "冷峻",
            "total_chapters": 120,
            "volumes": [
                {
                    "volume_name": "第二卷",
                    "start_chapter": 31,
                    "end_chapter": 60,
                    "core_conflict": "寻找内鬼",
                }
            ],
        },
        memory_context="上一章发现了密信",
    )
    assert "第二卷" in prompt
    assert "寻找内鬼" in prompt
    assert "上一章发现了密信" in prompt


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ({}, "outline_node"),
        (
            {"total_outline": {"total_chapters": 10}, "current_chapter_index": 0},
            "chapter_outline_node",
        ),
        (
            {
                "total_outline": {"total_chapters": 10},
                "current_chapter_index": 0,
                "chapter_outlines": [{"chapter_number": 1}],
            },
            "chapter_writer_node",
        ),
        (
            {
                "total_outline": {"total_chapters": 10},
                "current_chapter_index": 0,
                "current_chapter_content": "正文",
            },
            "reflection_node",
        ),
        (
            {
                "total_outline": {"total_chapters": 10},
                "current_chapter_index": 1,
                "memory_context": "",
            },
            "memory_retrieval_node",
        ),
    ],
)
def test_deterministic_router_follows_creation_flow(state, expected):
    assert _route(state)[0] == expected


@pytest.mark.asyncio
async def test_failed_run_reuses_checkpoint_quota_key():
    run_id = uuid4()
    context = TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )
    orchestrator = SimpleNamespace(
        set_auto_mode=lambda *_args: None,
        get_workflow_run_id=AsyncMock(return_value=str(run_id)),
    )
    quota = SimpleNamespace(reserve=AsyncMock())

    input_data, _, is_resume = await _prepare_request(
        WorkflowInvokeRequest(input={}),
        context,
        str(uuid4()),
        orchestrator,
        quota,
    )

    assert is_resume is False
    assert input_data["workflow_run_id"] == str(run_id)
    assert quota.reserve.await_args.args[1] == str(run_id)


def test_provider_524_is_safe_and_retryable():
    error = RuntimeError("private upstream details")
    error.status_code = 524
    error.body = {"retry_after": 120}
    payload = _public_error_data(error)
    assert payload == {
        "code": "provider_timeout",
        "message": "模型服务生成超时，请重试当前步骤",
        "retryable": True,
        "retry_after": 120,
    }
    assert "private" not in payload["message"]
