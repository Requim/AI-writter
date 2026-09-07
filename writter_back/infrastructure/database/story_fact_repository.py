"""复用现有会话工厂，按小说行锁串行化事实版本写入。"""

from uuid import UUID
from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.models import (
    NovelModel, StoryEntityModel, StoryFactAssertionModel, StoryFactVersionModel,
)
from service.ports.story_fact_repository import FactVersionConflictError
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.story_fact import CanonicalFact, FactStatement, Predicate, StoryEntity, StoryFactAssertion, StoryFactVersion

Contract = TypeVar("Contract", bound=BaseModel)

def _scoped(model: Any, tenant_id: str, novel_id: str) -> Any:
    return select(model).where(model.tenant_id == UUID(str(tenant_id)), model.novel_id == UUID(str(novel_id)))


def _contract(model: type[Contract], row: Any) -> Contract:
    return model.model_validate({name: getattr(row, name) for name in model.model_fields})


def _values(contract: BaseModel) -> dict[str, Any]:
    return contract.model_dump()


async def _authorize(session: AsyncSession, tenant_id: str, novel_id: str, *, lock: bool = False) -> None:
    query = select(NovelModel.id).where(NovelModel.tenant_id == UUID(str(tenant_id)), NovelModel.id == UUID(str(novel_id)))
    if lock:
        query = query.with_for_update()
    if await session.scalar(query) is None:
        raise ValueError("小说不存在或不可访问")


async def _check_entities(session: AsyncSession, tenant_id: str, novel_id: str, statement: FactStatement) -> None:
    ids = {statement.subject_id}
    if statement.object_entity_id:
        ids.add(statement.object_entity_id)
    rows = (await session.scalars(_scoped(StoryEntityModel, tenant_id, novel_id).where(StoryEntityModel.id.in_(ids)))).all()
    if {row.id for row in rows} != ids:
        raise ValueError("事实引用的实体不存在或不可访问")
    kinds = {row.id: row.kind for row in rows}
    expected = {"surname": ("character", None), "family": ("character", "family"),
                "ancestral_hall_owner": ("place", "family"), "location": (None, "place"), "life_status": ("character", None)}
    subject_kind, object_kind = expected[statement.predicate]
    if subject_kind and kinds[statement.subject_id] != subject_kind:
        raise ValueError("事实主体类型不匹配")
    if object_kind and kinds[statement.object_entity_id] != object_kind:
        raise ValueError("事实关系目标类型不匹配")


class PostgresStoryFactRepository:
    """内部事实数据接口；调用方须先确认来源，不能直接接收模型的自报权威。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.async_session = session_factory

    async def ingest_confirmed_facts(self, tenant_id: str, novel_id: str, entities: list[StoryEntity],
                                     facts: list[CanonicalFact], *, source_key: str) -> list[StoryFactVersion]:
        """原子导入可信服务确认的事实；重试复用，任何定义冲突均整批回滚。"""
        if not isinstance(source_key, str) or not source_key.strip() or len(source_key) > 64:
            raise ValueError("确认来源键必须非空且不超过64字符")
        entities = [StoryEntity.model_validate(item.model_dump()) for item in entities]
        facts = [CanonicalFact.model_validate(item.model_dump()) for item in facts]
        if len({item.id for item in entities}) != len(entities) or len({item.entity_key for item in entities}) != len(entities):
            raise ValueError("确认来源包含重复实体")
        if len({(item.subject_id, item.predicate) for item in facts}) != len(facts):
            raise ValueError("确认来源包含重复事实")
        async with self.async_session() as session, session.begin():
            await _authorize(session, tenant_id, novel_id, lock=True)
            for entity in entities:
                await self._ingest_entity(session, tenant_id, novel_id, entity)
            return [await self._ingest_fact(session, tenant_id, novel_id, fact, source_key) for fact in facts]

    async def _ingest_entity(self, session: AsyncSession, tenant_id: str, novel_id: str, entity: StoryEntity) -> None:
        row = await session.scalar(_scoped(StoryEntityModel, tenant_id, novel_id).where(StoryEntityModel.entity_key == entity.entity_key))
        if row is not None:
            if _contract(StoryEntity, row) != entity:
                raise FactVersionConflictError("已确认人物身份已变化，须先完成事实纠错")
            return
        session.add(StoryEntityModel(tenant_id=UUID(tenant_id), novel_id=UUID(novel_id), **_values(entity)))
        await session.flush()

    async def _ingest_fact(self, session: AsyncSession, tenant_id: str, novel_id: str,
                           fact: CanonicalFact, source_key: str) -> StoryFactVersion:
        await _check_entities(session, tenant_id, novel_id, fact)
        if fact.status != "confirmed":
            raise ValueError("确认入账不能撤回事实，须使用版本修正流程")
        model = StoryFactVersionModel
        key = f"{source_key}:{fact.subject_id}:{fact.predicate}"
        query = _scoped(model, tenant_id, novel_id)
        prior = await session.scalar(query.where(model.idempotency_key == key))
        if prior is not None and _contract(CanonicalFact, prior) != fact:
            raise FactVersionConflictError("确认来源已用于不同内容")
        current = await session.scalar(query.where(model.subject_id == fact.subject_id,
            model.predicate == fact.predicate).order_by(model.version.desc()).limit(1))
        if current is not None:
            if _contract(CanonicalFact, current).model_dump(exclude={"evidence"}) != fact.model_dump(exclude={"evidence"}):
                raise FactVersionConflictError("已确认事实存在冲突，须先完成事实纠错")
            return _contract(StoryFactVersion, current)
        row = StoryFactVersionModel(tenant_id=UUID(tenant_id), novel_id=UUID(novel_id),
            version=1, idempotency_key=key, **_values(fact))
        session.add(row)
        await session.flush()
        return _contract(StoryFactVersion, row)

    async def _capture_constraints(self, session: AsyncSession, tenant_id: str,
                                   novel_id: str, chapter_number: int) -> ChapterConstraintSet:
        if await session.scalar(text("SHOW transaction_isolation")) != "read committed":
            raise ValueError("章节事实复验要求 READ COMMITTED 事务隔离级别")
        await _authorize(session, tenant_id, novel_id, lock=True)
        entities = await session.scalars(_scoped(StoryEntityModel, tenant_id, novel_id))
        model = StoryFactVersionModel
        query = _scoped(model, tenant_id, novel_id).distinct(model.subject_id, model.predicate)
        facts = await session.scalars(query.order_by(model.subject_id, model.predicate, model.version.desc()))
        return ChapterConstraintSet(tenant_id=UUID(str(tenant_id)), novel_id=UUID(str(novel_id)),
            chapter_number=chapter_number, entities=tuple(_contract(StoryEntity, row) for row in entities),
            fact_heads=tuple(_contract(StoryFactVersion, row) for row in facts))

    async def capture_constraints(self, tenant_id: str, novel_id: str, chapter_number: int) -> ChapterConstraintSet:
        """在同一小说行锁内读取实体和版本头，避免生成混合版本的章节输入。"""
        async with self.async_session() as session, session.begin():
            return await self._capture_constraints(session, tenant_id, novel_id, chapter_number)

    async def assert_constraints_current(self, session: AsyncSession, tenant_id: str, novel_id: str,
                                         chapter_number: int, snapshot: ChapterConstraintSet) -> None:
        """必须在章节写入事务内调用；小说锁保留至调用方提交，禁止单独复验后另开事务写入。"""
        if not session.in_transaction():
            raise ValueError("事实快照复验必须在章节写入事务内执行")
        snapshot = ChapterConstraintSet.model_validate(snapshot.model_dump())
        if (snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number) != (
            UUID(str(tenant_id)), UUID(str(novel_id)), chapter_number,
        ):
            raise FactVersionConflictError("章节快照归属或章节不匹配")
        current = await self._capture_constraints(session, tenant_id, novel_id, chapter_number)
        if current.digest != snapshot.digest:
            raise FactVersionConflictError("章节事实约束已变化，请重新生成或复验")

    async def ensure_entity(self, tenant_id: str, novel_id: str, entity: StoryEntity) -> StoryEntity:
        """精确复用实体键；不允许重试覆盖姓名或类型。"""
        entity = StoryEntity.model_validate(entity.model_dump())
        async with self.async_session() as session, session.begin():
            await _authorize(session, tenant_id, novel_id, lock=True)
            row = await session.scalar(_scoped(StoryEntityModel, tenant_id, novel_id).where(StoryEntityModel.entity_key == entity.entity_key))
            if row:
                current = _contract(StoryEntity, row)
                if current.model_dump(exclude={"id"}) != entity.model_dump(exclude={"id"}):
                    raise FactVersionConflictError("实体键已存在且内容不同")
                return current
            row = StoryEntityModel(tenant_id=UUID(str(tenant_id)), novel_id=UUID(str(novel_id)), **_values(entity))
            session.add(row)
            await session.flush()
            return _contract(StoryEntity, row)

    async def append_fact(self, tenant_id: str, novel_id: str, fact: CanonicalFact, *,
                          expected_version: int, idempotency_key: str) -> StoryFactVersion:
        """追加事实历史；按小说加锁，拒绝过期版本和幂等键复用。"""
        fact = CanonicalFact.model_validate(fact.model_dump())
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("期望版本必须为非负整数")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 128:
            raise ValueError("幂等键必须为非空且不超过128字符")
        async with self.async_session() as session, session.begin():
            await _authorize(session, tenant_id, novel_id, lock=True)
            await _check_entities(session, tenant_id, novel_id, fact)
            query = _scoped(StoryFactVersionModel, tenant_id, novel_id)
            prior = await session.scalar(query.where(StoryFactVersionModel.idempotency_key == idempotency_key))
            if prior:
                if _contract(CanonicalFact, prior) != fact or prior.version != expected_version + 1:
                    raise FactVersionConflictError("幂等键已用于不同事实请求")
                return _contract(StoryFactVersion, prior)
            latest = await session.scalar(query.where(StoryFactVersionModel.subject_id == fact.subject_id,
                StoryFactVersionModel.predicate == fact.predicate).order_by(StoryFactVersionModel.version.desc()).limit(1))
            if (latest.version if latest else 0) != expected_version:
                raise FactVersionConflictError("事实版本已变化，请重新核对")
            row = StoryFactVersionModel(tenant_id=UUID(str(tenant_id)), novel_id=UUID(str(novel_id)),
                version=expected_version + 1, idempotency_key=idempotency_key, **_values(fact))
            session.add(row)
            await session.flush()
            return _contract(StoryFactVersion, row)

    async def list_current(self, tenant_id: str, novel_id: str) -> list[StoryFactVersion]:
        """按实体和属性读取最新版本，不隐去撤回记录。"""
        model = StoryFactVersionModel
        async with self.async_session() as session:
            await _authorize(session, tenant_id, novel_id)
            query = _scoped(model, tenant_id, novel_id).distinct(model.subject_id, model.predicate)
            rows = await session.scalars(query.order_by(model.subject_id, model.predicate, model.version.desc()))
            return [_contract(StoryFactVersion, row) for row in rows]

    async def list_history(self, tenant_id: str, novel_id: str, subject_id: UUID, predicate: Predicate) -> list[StoryFactVersion]:
        """返回指定事实的完整修订历史。"""
        model = StoryFactVersionModel
        async with self.async_session() as session:
            await _authorize(session, tenant_id, novel_id)
            rows = await session.scalars(_scoped(model, tenant_id, novel_id).where(
                model.subject_id == subject_id, model.predicate == predicate).order_by(model.version))
            return [_contract(StoryFactVersion, row) for row in rows]

    async def list_entities(self, tenant_id: str, novel_id: str) -> list[StoryEntity]:
        """读取当前小说实体，不返回其他小说或租户的数据。"""
        async with self.async_session() as session:
            await _authorize(session, tenant_id, novel_id)
            rows = await session.scalars(_scoped(StoryEntityModel, tenant_id, novel_id).order_by(StoryEntityModel.entity_key))
            return [_contract(StoryEntity, row) for row in rows]

    async def record_assertion(self, tenant_id: str, novel_id: str, assertion: StoryFactAssertion) -> StoryFactAssertion:
        """按断言ID保存证据，重复请求仅在内容完全相同的情况下复用。"""
        assertion = StoryFactAssertion.model_validate(assertion.model_dump())
        async with self.async_session() as session, session.begin():
            await _authorize(session, tenant_id, novel_id, lock=True)
            await _check_entities(session, tenant_id, novel_id, assertion)
            row = await session.scalar(_scoped(StoryFactAssertionModel, tenant_id, novel_id).where(StoryFactAssertionModel.id == assertion.id))
            if row:
                if _contract(StoryFactAssertion, row) != assertion:
                    raise FactVersionConflictError("断言ID已用于不同内容")
                return assertion
            session.add(StoryFactAssertionModel(tenant_id=UUID(str(tenant_id)), novel_id=UUID(str(novel_id)), **_values(assertion)))
            return assertion

    async def list_assertions(self, tenant_id: str, novel_id: str, chapter_number: int) -> list[StoryFactAssertion]:
        """读取某章的候选断言，不改变规范事实。"""
        async with self.async_session() as session:
            await _authorize(session, tenant_id, novel_id)
            rows = await session.scalars(_scoped(StoryFactAssertionModel, tenant_id, novel_id).where(
                StoryFactAssertionModel.chapter_number == chapter_number).order_by(StoryFactAssertionModel.id))
            return [_contract(StoryFactAssertion, row) for row in rows]
