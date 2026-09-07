"""LangGraph检查点与业务写入共用小说行锁，阻止旧租约提交。"""
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
import hashlib
import json
from uuid import uuid4
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.postgres import _ainternal
from application.execution_fence import execution_fence, ExecutionLeaseLost


class FencedPostgresSaver(AsyncPostgresSaver):
    async def setup(self) -> None:
        previous = execution_fence.set(None)
        try:
            await super().setup()
        finally:
            execution_fence.reset(previous)

    async def aput(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        result = await super().aput(config, checkpoint, metadata, new_versions)
        owner = execution_fence.get()
        if owner is not None:
            payload = json.dumps({"checkpoint_id": checkpoint["id"], "step": metadata.get("step"),
                "source": metadata.get("source")}, sort_keys=True)
            async with self._cursor() as cursor:
                await cursor.execute("INSERT INTO workflow_artifacts (id,tenant_id,novel_id,run_id,checkpoint_id,kind,digest,payload,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,now())",
                    (uuid4(), owner.tenant_id, owner.novel_id, owner.run_id, checkpoint["id"], "checkpoint",
                     hashlib.sha256(payload.encode()).hexdigest(), payload))
        return result

    @asynccontextmanager
    async def _cursor(self, *, pipeline: bool = False) -> AsyncIterator[Any]:
        owner = execution_fence.get()
        if owner is None:
            async with super()._cursor(pipeline=pipeline) as cursor:
                yield cursor
            return
        async with self.lock, _ainternal.get_connection(self.conn) as connection:
            async with connection.transaction(), connection.cursor(binary=True, row_factory=dict_row) as cursor:
                await cursor.execute('SELECT id FROM novels WHERE tenant_id=%s AND id=%s FOR UPDATE', (owner.tenant_id, owner.novel_id))
                if await cursor.fetchone() is None:
                    raise ExecutionLeaseLost('小说不存在')
                await cursor.execute('SELECT fence FROM workflow_leases WHERE tenant_id=%s AND novel_id=%s AND fence=%s AND token=%s AND expires_at>clock_timestamp()',
                    (owner.tenant_id, owner.novel_id, owner.fence, owner.token))
                if await cursor.fetchone() is None:
                    raise ExecutionLeaseLost('检查点执行租约已失效')
                yield cursor
