"""节点耗时仅记录名称、结果和时长，不记录Prompt或模型响应。"""
import inspect
import logging
import time
from functools import wraps
from typing import Any
from langgraph.errors import GraphInterrupt
from application.streaming import emit_workflow_event


def measured_node(name: str, node: Any) -> Any:
    accepts_config = 'config' in inspect.signature(node).parameters

    @wraps(node)
    async def measured(state: Any, config: Any = None) -> Any:
        started = time.perf_counter()
        outcome = 'completed'
        try:
            result = node(state, config=config) if accepts_config else node(state)
            return await result if inspect.isawaitable(result) else result
        except BaseException as error:
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
