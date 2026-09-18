"""节点耗时仅记录名称、结果和时长，不记录Prompt或模型响应。"""
import inspect
import logging
import time
import asyncio
from functools import wraps
from typing import Any
from langgraph.errors import GraphInterrupt
from application.streaming import emit_workflow_event
from application.errors import WorkflowNodeTimeoutError
from config import settings


def _node_timeout(config: Any) -> float:
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    if configurable.get("auto_mode", False):
        return settings.WORKFLOW_BACKGROUND_NODE_TIMEOUT_SECONDS
    return settings.WORKFLOW_NODE_TIMEOUT_SECONDS


def measured_node(name: str, node: Any) -> Any:
    accepts_config = 'config' in inspect.signature(node).parameters

    @wraps(node)
    async def measured(state: Any, config: Any = None) -> Any:
        started = time.perf_counter()
        outcome = 'completed'
        timeout_seconds = _node_timeout(config)
        try:
            result = node(state, config=config) if accepts_config else node(state)
            if not inspect.isawaitable(result):
                return result
            deadline = asyncio.timeout(timeout_seconds)
            try:
                async with deadline:
                    return await result
            except TimeoutError as error:
                if not deadline.expired():
                    raise
                outcome = 'timeout'
                raise WorkflowNodeTimeoutError(
                    name, timeout_seconds
                ) from error
        except BaseException as error:
            if outcome != 'timeout':
                outcome = 'interrupted' if isinstance(error, GraphInterrupt) else 'failed'
            raise
        finally:
            _record_measurement(name, outcome, time.perf_counter() - started)
    return measured


def _record_measurement(name: str, outcome: str, duration: float) -> None:
    try:
        emit_workflow_event('status', {'status': 'measurement', 'outcome': outcome,
            'duration_seconds': round(duration, 4)}, name)
    except Exception:
        logging.getLogger('uvicorn').warning('node_measurement_emit_failed node=%s', name)
