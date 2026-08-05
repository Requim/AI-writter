"""Schema 5 nodes must stop before model calls when planning is disabled."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from application.agents.chapter_compaction_node import chapter_compaction_node
from application.agents.chapter_writer_node import chapter_writer_node
from application.agents.reflection_node import reflection_node
from application.agents.revision_node import revision_node
from application.errors import PlanningTemporarilyDisabledError
from application.feature_policy import FeaturePolicy, require_planning_v1
from service.entities.identity import TenantContext


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(), tenant_name="测试租户", user_id=uuid4(),
        role="owner", is_platform_admin=False, ai_enabled=True,
        monthly_generation_limit=30, novel_planning_v1_enabled=True,
    )


def _runtime() -> tuple[dict, SimpleNamespace, AsyncMock]:
    llm = SimpleNamespace(
        generate=AsyncMock(), structured_generate=AsyncMock(), stream_text=Mock(),
    )
    loader = AsyncMock(return_value=False)
    policy = FeaturePolicy(SimpleNamespace(
        NOVEL_PLANNING_V1_ENABLED=True,
        WORKFLOW_REVIEW_V3_ENABLED=False,
    ))
    config = {"configurable": {
        "feature_policy": policy,
        "tenant_context": _context(),
        "tenant_planning_loader": loader,
        "novel_planning_v1_enabled": True,
        "adaptive_compaction_enabled": True,
        "llm_config": {"llm_instance": llm},
    }}
    return config, llm, loader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node",
    [chapter_writer_node, chapter_compaction_node, reflection_node, revision_node],
)
async def test_schema5_generation_nodes_stop_before_llm(node) -> None:
    config, llm, loader = _runtime()

    with pytest.raises(PlanningTemporarilyDisabledError):
        await node({"workflow_schema_version": 5}, config)

    loader.assert_awaited_once()
    llm.generate.assert_not_awaited()
    llm.structured_generate.assert_not_awaited()
    llm.stream_text.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_schema_does_not_require_planning_v1() -> None:
    config, _llm, loader = _runtime()

    await require_planning_v1(config, workflow_schema_version=4)

    loader.assert_not_awaited()
