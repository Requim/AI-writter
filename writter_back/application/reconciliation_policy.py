"""恢复失败指数退避；达到上限后保留死信，禁止无限重试。"""
import time
from typing import Any


def recovery_ready(request: dict[str, Any]) -> bool:
    recovery = request.get('_recovery') or {}
    return recovery.get('status') != 'dead_letter' and float(recovery.get('next_attempt_at', 0)) <= time.time()


def deferred_request(request: dict[str, Any], error_code: str) -> dict[str, Any]:
    attempt = int((request.get('_recovery') or {}).get('attempt', 0)) + 1
    recovery = {'attempt': attempt, 'status': 'dead_letter' if attempt >= 5 else 'backoff',
        'next_attempt_at': time.time() + min(300, 5 * 2 ** (attempt - 1)), 'error_code': error_code}
    return {**request, '_recovery': recovery}
