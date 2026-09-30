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
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot
from application.creative.errors import CreativePause
from application.creative.runtime import run_creative_node, pause_creative


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
        token = set_prompt_snapshot(
            state.get("prompt_snapshot") if isinstance(state, dict) else None
        )
        try:
            result = run_creative_node(name, node, accepts_config, state, config) if state.get("author_mode") == "autonomous_v1" else (
                node(state, config=config) if accepts_config else node(state)
            )
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
        except CreativePause as error:
            outcome = "interrupted"
            return pause_creative(error, name)
        except BaseException as error:
            if outcome != 'timeout':
                outcome = 'interrupted' if isinstance(error, GraphInterrupt) else 'failed'
            raise
        finally:
            reset_prompt_snapshot(token)
            _record_measurement(name, outcome, time.perf_counter() - started)
    return measured


def _record_measurement(name: str, outcome: str, duration: float) -> None:
    try:
        emit_workflow_event('status', {'status': 'measurement', 'outcome': outcome,
            'duration_seconds': round(duration, 4)}, name)
    except Exception:
        logging.getLogger('uvicorn').warning('node_measurement_emit_failed node=%s', name)
