"""Platform administrator tenant and account controls."""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from api.dependencies import get_identity_repository, require_platform_admin
from api.tenant_features import tenant_feature_status
from infrastructure.database.identity_repository import IdentityRepository
from service.entities.identity import CurrentUser

router = APIRouter()


def current_period_start() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date().replace(day=1)


class TenantAdminUpdate(BaseModel):
    status: Literal["active", "suspended"] | None = None
    ai_enabled: bool | None = None
    monthly_generation_limit: int | None = Field(default=None, ge=0, le=100000)
    monthly_generation_unlimited: bool | None = None
    novel_planning_v1_enabled: bool | None = None

    @model_validator(mode="after")
    def require_limit_when_disabling_unlimited(self) -> "TenantAdminUpdate":
        if (
            self.monthly_generation_unlimited is False
            and self.monthly_generation_limit is None
        ):
            raise ValueError("关闭无限额度时必须同时设置月度额度")
        return self


class UserAdminUpdate(BaseModel):
    status: Literal["active", "suspended"]


@router.get("/tenants")
async def tenants(
    _admin: CurrentUser = Depends(require_platform_admin),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> list[dict[str, Any]]:
    items = await identity.admin_list_tenants(current_period_start())
    return [tenant_feature_status(item) for item in items]


@router.get("/users")
async def users(
    _admin: CurrentUser = Depends(require_platform_admin),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> list[dict[str, Any]]:
    return await identity.admin_list_users()


@router.patch("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: UUID,
    request: TenantAdminUpdate,
    admin: CurrentUser = Depends(require_platform_admin),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    values = request.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=422, detail="没有可更新的字段")
    if not await identity.admin_update_tenant(admin.id, tenant_id, values):
        raise HTTPException(status_code=404, detail="租户不存在")
    response = {"tenant_id": str(tenant_id), **values}
    if "novel_planning_v1_enabled" in values:
        return tenant_feature_status(response)
    return response


@router.patch("/users/{user_id}")
async def update_user(
    user_id: UUID,
    request: UserAdminUpdate,
    admin: CurrentUser = Depends(require_platform_admin),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, str]:
    if user_id == admin.id and request.status != "active":
        raise HTTPException(status_code=409, detail="不能停用当前平台管理员")
    if not await identity.admin_update_user_status(user_id, request.status):
        raise HTTPException(status_code=404, detail="账号不存在")
    return {"user_id": str(user_id), "status": request.status}
