import asyncio

import pytest

from application.errors import WorkflowNodeTimeoutError
from application.runtime_observability import measured_node


@pytest.mark.asyncio
async def test_measured_node_raises_named_retryable_timeout(monkeypatch):
    from application.runtime_observability import settings

    monkeypatch.setattr(settings, "WORKFLOW_NODE_TIMEOUT_SECONDS", 0.01)

    async def slow_node(_state, config=None):
        await asyncio.sleep(1)

    wrapped = measured_node("character_design_node", slow_node)
    with pytest.raises(WorkflowNodeTimeoutError) as raised:
        await wrapped({}, config={})

    assert raised.value.code == "workflow_node_timeout"
    assert raised.value.node == "character_design_node"
    assert raised.value.timeout_seconds == 0.01
