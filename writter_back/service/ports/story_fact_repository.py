"""事实仓储端口；写入必须明确小说归属、来源与期望版本。"""

from typing import Protocol

from service.value_objects.story_fact import CanonicalFact, StoryEntity, StoryFactAssertion, StoryFactVersion


class FactVersionConflictError(ValueError):
    """事实版本或幂等请求内容冲突，不允许静默覆盖。"""


class StoryFactRepository(Protocol):
    async def ensure_entity(self, tenant_id: str, novel_id: str, entity: StoryEntity) -> StoryEntity:
        """新增或精确复用小说实体，不原地改写已有实体。"""
        ...

    async def append_fact(
        self, tenant_id: str, novel_id: str, fact: CanonicalFact, *, expected_version: int, idempotency_key: str,
    ) -> StoryFactVersion:
        """以期望版本追加事实；同一请求可安全重放。"""
        ...

    async def list_current(self, tenant_id: str, novel_id: str) -> list[StoryFactVersion]:
        """读取各事实最新版本，包括撤回标记。"""
        ...

    async def record_assertion(self, tenant_id: str, novel_id: str, assertion: StoryFactAssertion) -> StoryFactAssertion:
        """保留待验证的正文断言，不将其自动提升为规范事实。"""
        ...
