"""会话控制命令与结果同事务入账，重放不依赖最后一次配置。"""

from sqlalchemy import select

from application.creative.errors import CreativeConflict
from infrastructure.database.creative_models import CreativeRecordModel
from infrastructure.database.creative_repository import _digest
from infrastructure.database.models import NovelModel, TenantModel


async def replay_control(session, tenant, novel, key, command):
    """在持有小说行锁时检查所有历史幂等键。"""
    row = await session.scalar(select(CreativeRecordModel).where(
        CreativeRecordModel.tenant_id == tenant, CreativeRecordModel.novel_id == novel,
        CreativeRecordModel.idempotency_key == key,
    ))
    if row is None:
        return None
    if row.kind != "control" or row.digest != _digest(command):
        raise CreativeConflict("同一幂等键对应不同控制命令")
    return row.payload["result"]


def record_control(session, tenant, novel, key, command, result):
    """控制变更成功后在同一事务保存原始响应，支持跨请求重放。"""
    session.add(CreativeRecordModel(
        tenant_id=tenant, novel_id=novel, kind="control", key=_digest(key),
        version=1, idempotency_key=key, digest=_digest(command),
        payload={"command": command, "result": result}, status="accepted",
        source="author", input_versions={}, evidence=[],
    ))


async def replay_creation(session, tenant, novel, key, command):
    """新书不存在时以租户行锁串行化相同创建命令，避免先查后写竞态。"""
    await session.scalar(select(TenantModel).where(TenantModel.id == tenant).with_for_update())
    exists = await session.scalar(select(NovelModel.id).where(
        NovelModel.tenant_id == tenant, NovelModel.id == novel,
    ))
    if exists is None:
        return False
    previous = await replay_control(session, tenant, novel, key, command)
    if previous is None:
        raise CreativeConflict("新书标识已存在，不能覆盖已有作品")
    return True
