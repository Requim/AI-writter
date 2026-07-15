"""Tenant switching, usage and membership management endpoints."""

from datetime import date, datetime, timedelta, timezone
import secrets
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import (
    get_auth_service,
    get_current_user,
    get_identity_repository,
    get_tenant_context,
)
from application.auth_service import AuthService
from config import settings
from infrastructure.database.identity_repository import IdentityRepository
from service.entities.identity import CurrentUser, TenantContext

router = APIRouter()


def current_period_start() -> date:
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return now.date().replace(day=1)


class InvitationRequest(BaseModel):
    role: Literal["admin", "member"] = "member"


class RoleUpdateRequest(BaseModel):
    role: Literal["admin", "member"]


class TenantUpdateRequest(BaseModel):
    name: str


@router.get("")
async def list_tenants(
    user: CurrentUser = Depends(get_current_user),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> list[dict[str, Any]]:
    return await identity.list_tenants(user.id)


@router.get("/current/usage")
async def current_usage(
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    used = await identity.quota_usage(context.tenant_id, current_period_start())
    return {
        "used": used,
        "limit": context.monthly_generation_limit,
        "remaining": max(context.monthly_generation_limit - used, 0),
        "ai_enabled": context.ai_enabled,
        "period_start": current_period_start(),
    }


@router.get("/current/members")
async def members(
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> list[dict[str, Any]]:
    return await identity.list_members(context.tenant_id)


@router.patch("/current")
async def update_tenant(
    request: TenantUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, str]:
    if context.role != "owner":
        raise HTTPException(status_code=403, detail="只有 Owner 可以修改租户")
    name = request.name.strip()
    if not 2 <= len(name) <= 120:
        raise HTTPException(status_code=422, detail="工作区名称长度必须为 2 到 120 个字符")
    await identity.admin_update_tenant(context.user_id, context.tenant_id, {"name": name})
    return {"id": str(context.tenant_id), "name": name}


@router.post("/current/invitations", status_code=201)
async def invite(
    request: InvitationRequest,
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
    auth: AuthService = Depends(get_auth_service),
) -> dict[str, Any]:
    if not context.can_manage_members():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    if context.role == "admin" and request.role == "admin":
        raise HTTPException(status_code=403, detail="只有 Owner 可以邀请 Admin")
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.INVITATION_DAYS)
    invitation = await identity.create_invitation(
        context,
        auth.token_hash(token),
        request.role,
        expires_at,
    )
    return {
        "id": str(invitation.id),
        "token": token,
        "invite_path": f"/invite/{token}",
        "role": request.role,
        "expires_at": expires_at,
    }


@router.post("/invitations/{token}/accept")
async def accept_invitation(
    token: str,
    user: CurrentUser = Depends(get_current_user),
    identity: IdentityRepository = Depends(get_identity_repository),
    auth: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    tenant_id = await identity.accept_invitation(auth.token_hash(token), user.id)
    if tenant_id is None:
        raise HTTPException(status_code=410, detail="邀请已失效或已被使用")
    return {"tenant_id": str(tenant_id), "status": "joined"}


@router.patch("/current/members/{user_id}")
async def update_member_role(
    user_id: UUID,
    request: RoleUpdateRequest,
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, str]:
    if context.role != "owner":
        raise HTTPException(status_code=403, detail="只有 Owner 可以调整成员角色")
    if user_id == context.user_id:
        raise HTTPException(status_code=409, detail="不能修改自己的 Owner 角色")
    if not await identity.update_member_role(context, user_id, request.role):
        raise HTTPException(status_code=404, detail="成员不存在")
    return {"user_id": str(user_id), "role": request.role}


@router.post("/current/ownership/{user_id}")
async def transfer_ownership(
    user_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, str]:
    if context.role != "owner" or user_id == context.user_id:
        raise HTTPException(status_code=403, detail="只有 Owner 可以转让所有权")
    if not await identity.transfer_ownership(context, user_id):
        raise HTTPException(status_code=404, detail="目标成员不存在")
    return {"owner_user_id": str(user_id), "status": "transferred"}


@router.delete("/current/members/{user_id}", status_code=204)
async def remove_member(
    user_id: UUID,
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> None:
    if not context.can_manage_members():
        raise HTTPException(status_code=403, detail="需要租户管理员权限")
    if user_id == context.user_id:
        raise HTTPException(status_code=409, detail="请使用退出租户操作")
    if not await identity.remove_member(context, user_id):
        raise HTTPException(status_code=404, detail="成员不存在或不可移除")


@router.delete("/current/membership", status_code=204)
async def leave_tenant(
    context: TenantContext = Depends(get_tenant_context),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> None:
    if context.role == "owner":
        raise HTTPException(status_code=409, detail="Owner 转让所有权后才能退出")
    if not await identity.remove_member(context, context.user_id):
        raise HTTPException(status_code=404, detail="成员关系不存在")
