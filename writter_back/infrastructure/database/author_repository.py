"""租户作者样例与档案的不可变版本仓储。"""

from uuid import UUID

from sqlalchemy import select

from application.creative.author_style import validate_profile_sources
from application.creative.errors import CreativeConflict
from infrastructure.database.creative_models import AuthorRecordModel
from infrastructure.database.creative_repository import _digest, row_dict
from infrastructure.database.models import NovelModel, TenantModel
from service.value_objects.author_style import AuthorProfile, AuthorSample


class PostgresAuthorRepository:
    def __init__(self, session_factory):
        self.sessions = session_factory

    async def records(self, tenant_id: str, kind: str) -> list[dict]:
        async with self.sessions() as session:
            rows = await session.scalars(select(AuthorRecordModel).where(
                AuthorRecordModel.tenant_id == UUID(tenant_id), AuthorRecordModel.kind == kind,
            ).order_by(AuthorRecordModel.created_at, AuthorRecordModel.version))
            return [row_dict(row) for row in rows]

    async def put(self, tenant_id: str, kind: str, key: str, payload: dict, expected: int, idempotency_key: str) -> dict:
        """作者显式提交样例/档案；不从模型评分自动学习全局偏好。"""
        parsed = AuthorSample.model_validate(payload) if kind == "sample" else AuthorProfile.model_validate(payload)
        payload = parsed.model_dump(mode="json")
        digest = _digest({"kind": kind, "key": key, "payload": payload})
        async with self.sessions.begin() as session:
            tenant = UUID(tenant_id)
            await session.scalar(select(TenantModel.id).where(TenantModel.id == tenant).with_for_update())
            base = select(AuthorRecordModel).where(AuthorRecordModel.tenant_id == tenant)
            replay = await session.scalar(base.where(AuthorRecordModel.idempotency_key == idempotency_key))
            if replay:
                if replay.digest != digest:
                    raise CreativeConflict("作者档案幂等键对应不同请求")
                return row_dict(replay)
            current = await session.scalar(base.where(AuthorRecordModel.kind == kind, AuthorRecordModel.key == UUID(key)).order_by(AuthorRecordModel.version.desc()).limit(1))
            if (current.version if current else 0) != expected:
                raise CreativeConflict("作者档案版本已更新")
            if kind == "profile":
                rows = await session.scalars(base.where(AuthorRecordModel.kind == "sample"))
                validate_profile_sources(parsed, {str(row.key): row.payload for row in rows})
            elif current:
                raise ValueError("原创样例不可覆盖，请创建新样例并保留原稿对照")
            if kind == "sample":
                await _validate_book_scope(session, tenant, parsed.novel_id)
            row = AuthorRecordModel(
                tenant_id=tenant, kind=kind, key=UUID(key), version=expected + 1,
                idempotency_key=idempotency_key, digest=digest, payload=payload,
            )
            session.add(row)
            await session.flush()
            return row_dict(row)

    async def profile(self, tenant_id: str, profile_id: str, version: int) -> AuthorProfile:
        async with self.sessions() as session:
            row = await session.scalar(select(AuthorRecordModel).where(
                AuthorRecordModel.tenant_id == UUID(tenant_id), AuthorRecordModel.kind == "profile",
                AuthorRecordModel.key == UUID(profile_id), AuthorRecordModel.version == version,
            ))
            if row is None:
                raise LookupError("作者档案版本不存在或不属于当前租户")
            return AuthorProfile.model_validate(row.payload)


async def _validate_book_scope(session, tenant, novel_id):
    if novel_id is None:
        return
    exists = await session.scalar(select(NovelModel.id).where(
        NovelModel.id == novel_id, NovelModel.tenant_id == tenant,
    ))
    if exists is None:
        raise ValueError("本书原创样例所绑定的小说不属于当前租户")
