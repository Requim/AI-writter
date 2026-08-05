"""整书规划版本与执行记录仓储接口。"""

from abc import ABC, abstractmethod

from service.value_objects.novel_plan import (
    NovelPlan,
    NovelPlanVersionSummary,
    PlanExecution,
)


class PlanVersionConflictError(RuntimeError):
    """客户端基于过期计划版本提交了修改。"""


class NovelPlanRepository(ABC):
    @abstractmethod
    async def get_latest_plan(
        self, tenant_id: str, novel_id: str
    ) -> NovelPlan | None:
        pass

    @abstractmethod
    async def list_plan_versions(
        self, tenant_id: str, novel_id: str
    ) -> list[NovelPlan]:
        pass

    @abstractmethod
    async def list_plan_version_summaries(
        self, tenant_id: str, novel_id: str
    ) -> list[NovelPlanVersionSummary]:
        pass

    @abstractmethod
    async def accept_plan(
        self,
        tenant_id: str,
        novel_id: str,
        plan: NovelPlan,
        expected_version: int,
        *,
        created_by_user_id: str | None = None,
        trigger_chapter: int | None = None,
        change_summary: str = "",
    ) -> NovelPlan:
        pass

    @abstractmethod
    async def list_plan_executions(
        self, tenant_id: str, novel_id: str
    ) -> list[PlanExecution]:
        pass

    @abstractmethod
    async def upsert_plan_execution(
        self, tenant_id: str, novel_id: str, execution: PlanExecution
    ) -> PlanExecution:
        pass

    @abstractmethod
    async def delete_plan_executions_from(
        self, tenant_id: str, novel_id: str, chapter_number: int
    ) -> None:
        pass
