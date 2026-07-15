"""Idempotent monthly AI generation quota reservations."""

from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from infrastructure.database.identity_repository import IdentityRepository
from service.entities.identity import TenantContext


class QuotaService:
    def __init__(self, repository: IdentityRepository):
        self.repository = repository

    @staticmethod
    def current_period_start() -> date:
        return datetime.now(ZoneInfo("Asia/Shanghai")).date().replace(day=1)

    async def reserve(
        self,
        context: TenantContext,
        workflow_run_id: str | UUID,
        operation_type: str,
        chapter_index: int = -1,
    ) -> tuple[int, int]:
        run_id = (
            workflow_run_id
            if isinstance(workflow_run_id, UUID)
            else UUID(str(workflow_run_id))
        )
        return await self.repository.reserve_quota(
            context,
            run_id,
            operation_type,
            chapter_index,
            self.current_period_start(),
        )
