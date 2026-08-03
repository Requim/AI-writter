"""基于 Redis 的工作流命令幂等存储。"""

import hashlib
import math
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from redis.exceptions import RedisError

from service.ports.workflow_command_store import (
    WorkflowCommandClaim,
    WorkflowCommandClaimStatus,
    WorkflowCommandStore,
    WorkflowCommandStoreUnavailable,
)

_RUNNING_PREFIX = "running:"
_APPLIED_VALUE = "applied"
_FINALIZE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
  return 1
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisWorkflowCommandStore(WorkflowCommandStore):
    """使用独立租约令牌保护命令终态写入。"""

    def __init__(self, redis_url: str, client: Any | None = None) -> None:
        self._redis = (
            client
            if client is not None
            else Redis.from_url(redis_url, decode_responses=True)
        )

    @staticmethod
    def _key(tenant_id: str, novel_id: str, command_id: str) -> str:
        digest = hashlib.sha256(command_id.encode("utf-8")).hexdigest()
        return f"novel-writer:workflow-command:{tenant_id}:{novel_id}:{digest}"

    async def claim(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        ttl_seconds: float,
    ) -> WorkflowCommandClaim:
        key = self._key(tenant_id, novel_id, command_id)
        token = uuid4().hex
        running_value = f"{_RUNNING_PREFIX}{token}"
        try:
            acquired = await self._redis.set(
                key, running_value, ex=math.ceil(ttl_seconds), nx=True
            )
            if acquired:
                return WorkflowCommandClaim(
                    WorkflowCommandClaimStatus.ACQUIRED, token
                )
            current = await self._redis.get(key)
        except RedisError as exc:
            raise WorkflowCommandStoreUnavailable from exc
        status = (
            WorkflowCommandClaimStatus.ALREADY_APPLIED
            if current == _APPLIED_VALUE
            else WorkflowCommandClaimStatus.IN_PROGRESS
        )
        return WorkflowCommandClaim(status)

    async def finalize(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        lease_token: str,
        ttl_seconds: float,
    ) -> bool:
        key = self._key(tenant_id, novel_id, command_id)
        expected = f"{_RUNNING_PREFIX}{lease_token}"
        try:
            result = await self._redis.eval(
                _FINALIZE_SCRIPT,
                1,
                key,
                expected,
                _APPLIED_VALUE,
                math.ceil(ttl_seconds),
            )
        except RedisError as exc:
            raise WorkflowCommandStoreUnavailable from exc
        return bool(result)

    async def release(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        lease_token: str,
    ) -> bool:
        key = self._key(tenant_id, novel_id, command_id)
        expected = f"{_RUNNING_PREFIX}{lease_token}"
        try:
            result = await self._redis.eval(
                _RELEASE_SCRIPT, 1, key, expected
            )
        except RedisError as exc:
            raise WorkflowCommandStoreUnavailable from exc
        return bool(result)

    async def ping(self) -> None:
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise WorkflowCommandStoreUnavailable from exc

    async def aclose(self) -> None:
        await self._redis.aclose()
