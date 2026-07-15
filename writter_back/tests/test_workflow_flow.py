"""Tests for the deterministic macro-outline and per-chapter workflow."""

import asyncio
import ast
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from langgraph.graph import END, StateGraph

from api.routers.workflow_router import (
    WorkflowInvokeRequest,
    _prepare_request,
    _public_error_data,
)
from application.agents.router_agent import _route
from application.agents.router_agent import router_agent
from application.orchestrator import NovelOrchestrator
from application.prompts.chapter_outline_prompts import CHAPTER_OUTLINE_SCHEMA
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.prompts.outline_prompts import build_outline_prompt, validate_outline
from application.prompts.reflection_prompts import (
    AGGREGATION_SCHEMA,
    CHUNK_REFLECTION_SCHEMA,
    REFLECTION_SCHEMA,
)
from application.schemas.agent_state import NovelAgentState
from application.workflow_builder import WORKFLOW_NODES, create_novel_workflow
from service.entities.identity import TenantContext


def tenant_context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        tenant_name="测试租户",
        user_id=uuid4(),
        role="owner",
        is_platform_admin=False,
        ai_enabled=True,
        monthly_generation_limit=30,
    )


def orchestrator() -> NovelOrchestrator:
    return NovelOrchestrator(
        repository=SimpleNamespace(),
        memory_service=SimpleNamespace(),
        llm_config={},
    )


class FakeWorkflowLLM:
    def __init__(self) -> None:
        self.chapter_outline_calls = 0
        self.stream_calls = 0

    async def generate(self, *_args, **_kwargs) -> str:
        return "生成文本"

    async def structured_generate(self, prompt, schema, **_kwargs):
        del prompt
        if schema is CHAPTER_OUTLINE_SCHEMA:
            self.chapter_outline_calls += 1
            return {
                "chapter_number": 1,
                "title": "第一章 回声",
                "chapter_goal": "建立核心悬念",
                "core_conflict": "主角收到不可能存在的来信",
                "scenes": [],
                "estimated_word_count": 3200,
            }
        if schema is CHUNK_REFLECTION_SCHEMA:
            return {"issues": []}
        if schema is AGGREGATION_SCHEMA or schema is REFLECTION_SCHEMA:
            return {
                "passed": True,
                "overall_quality_score": 0.92,
                "word_count_analysis": {
                    "total_count": 3200,
                    "effective_density": 92,
                    "is_valid_word_count": True,
                },
                "issues": [],
                "logic_chain_status": "连贯",
                "foreshadowing_check": "有效",
            }
        raise AssertionError(f"Unexpected schema: {schema}")

    async def stream_text(self, *_args, **_kwargs):
        self.stream_calls += 1
        yield "正文" * 1600


def test_registered_nodes_use_langgraph_supported_signatures():
    for name, node in WORKFLOW_NODES.items():
        parameters = list(inspect.signature(node).parameters.values())
        assert parameters and parameters[0].name == "state", name
        if len(parameters) > 1:
            assert parameters[1].name == "config", name


def test_all_literal_command_targets_are_registered_nodes():
    agents_dir = Path(__file__).parents[1] / "application" / "agents"
    registered = set(WORKFLOW_NODES)
    targets: list[tuple[str, int, str]] = []
    for path in agents_dir.glob("*_node.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Command":
                continue
            goto = next((item.value for item in node.keywords if item.arg == "goto"), None)
            if isinstance(goto, ast.Constant) and isinstance(goto.value, str):
                targets.append((path.name, node.lineno, goto.value))
    invalid = [item for item in targets if item[2] not in registered]
    assert not invalid


@pytest.mark.asyncio
async def test_router_is_invoked_by_langgraph_with_config_contract():
    graph = StateGraph(NovelAgentState)
    graph.add_node("router_agent", router_agent)

    async def finish_node(_state):
        return {"phase": "captured"}

    for destination in (
        "outline_node",
        "memory_retrieval_node",
        "chapter_outline_node",
        "chapter_writer_node",
        "reflection_node",
    ):
        graph.add_node(destination, finish_node)
        graph.add_edge(destination, END)
    graph.set_entry_point("router_agent")

    result = await graph.compile().ainvoke(
        {
            "total_outline": {"total_chapters": 1},
            "current_chapter_index": 0,
            "chapter_outlines": [],
        }
    )
    assert result["next_tool"] == "chapter_outline_node"
    assert result["phase"] == "captured"


@pytest.mark.asyncio
async def test_fake_llm_completes_one_chapter_through_real_graph():
    llm = FakeWorkflowLLM()
    workflow = create_novel_workflow()
    result = await workflow.ainvoke(
        {
            "novel_type": "suspense",
            "title": "测试小说",
            "summary": "测试简介",
            "total_outline": {
                "story_background": "测试世界",
                "main_characters": [],
                "main_plot": {},
                "writing_style": "克制",
                "total_chapters": 1,
                "volumes": [],
            },
            "current_chapter_index": 0,
            "chapter_outlines": [],
            "completed_chapters": [],
            "current_chapter_content": "",
            "memory_context": "",
            "is_completed": False,
            "revision_attempts": 0,
            "errors": [],
        },
        {
            "recursion_limit": 40,
            "configurable": {
                "llm_config": {"llm_instance": llm},
                "auto_mode": True,
                "novel_id": "00000000-0000-0000-0000-000000000001",
                "tenant_id": "00000000-0000-0000-0000-000000000002",
                "novel_repository": None,
                "memory_service": None,
                "quota_service": None,
            },
        },
    )

    assert result["is_completed"] is True
    assert result["current_chapter_index"] == 1
    assert len(result["completed_chapters"]) == 1
    assert llm.chapter_outline_calls == 1
    assert llm.stream_calls == 1


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
        (
            {
                "total_outline": {"total_chapters": 10},
                "current_chapter_index": 1,
                "memory_context": "",
                "memory_retrieved_for_chapter": 1,
            },
            "chapter_outline_node",
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


@pytest.mark.asyncio
async def test_orphaned_lock_is_recovered_before_next_run():
    service = orchestrator()
    context = tenant_context()
    thread_id = str(uuid4())
    assert await service.try_start(context, thread_id) is True
    key = service.execution_key(context, thread_id)
    service._execution_snapshots[key]["started_at"] = "2020-01-01T00:00:00+00:00"

    assert await service.try_start(context, thread_id) is True
    service.finish(context, thread_id)


@pytest.mark.asyncio
async def test_cancel_waits_for_task_and_releases_lock():
    service = orchestrator()
    context = tenant_context()
    thread_id = str(uuid4())
    assert await service.try_start(context, thread_id) is True
    task = asyncio.create_task(asyncio.Event().wait())
    service.register_task(context, thread_id, task)

    assert await service.cancel(context, thread_id) is True
    assert task.cancelled()
    assert service.is_executing(context, thread_id) is False


@pytest.mark.asyncio
async def test_cancel_does_not_release_lock_during_registration_grace():
    service = orchestrator()
    context = tenant_context()
    thread_id = str(uuid4())
    assert await service.try_start(context, thread_id) is True

    assert await service.cancel(context, thread_id) is False
    assert service.is_executing(context, thread_id) is True
    service.finish(context, thread_id)


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
