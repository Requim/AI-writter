"""滚动战术计划版本仓储接口。"""

from abc import ABC, abstractmethod

from service.value_objects.tactical_plan import TacticalWindow


class TacticalPlanVersionConflictError(RuntimeError):
    """客户端基于过期战术版本提交了修改。"""


class TacticalPlanRepository(ABC):
    @abstractmethod
    async def get_latest_tactical_plan(
        self, tenant_id: str, novel_id: str
    ) -> TacticalWindow | None:
        pass

    @abstractmethod
    async def list_tactical_plan_versions(
        self, tenant_id: str, novel_id: str
    ) -> list[TacticalWindow]:
        pass

    @abstractmethod
    async def accept_tactical_plan(
        self,
        tenant_id: str,
        novel_id: str,
        window: TacticalWindow,
        expected_version: int,
        *,
        idempotency_key: str,
        created_by_user_id: str | None = None,
    ) -> TacticalWindow:
        pass
