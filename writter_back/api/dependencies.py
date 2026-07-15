"""Authenticated user and tenant dependencies shared by API routers."""

from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from application.auth_service import AuthService, AuthenticationError
from infrastructure.database.identity_repository import IdentityRepository
from service.entities.identity import CurrentUser, TenantContext

bearer = HTTPBearer(auto_error=False)


def get_identity_repository(request: Request) -> IdentityRepository:
    return request.app.state.identity_repository


def get_auth_service(request: Request) -> AuthService:
    return request.app.state.auth_service


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    auth: AuthService = Depends(get_auth_service),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> CurrentUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        user_id = auth.decode_access_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    user = await identity.current_user(user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="账号不可用")
    return user


async def get_tenant_context(
    tenant_header: str | None = Header(default=None, alias="X-Tenant-ID"),
    user: CurrentUser = Depends(get_current_user),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> TenantContext:
    if not tenant_header:
        raise HTTPException(status_code=400, detail="缺少 X-Tenant-ID")
    try:
        tenant_id = UUID(tenant_header)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID 格式不正确") from exc
    context = await identity.get_tenant_context(user, tenant_id)
    if context is None:
        raise HTTPException(status_code=403, detail="无权访问该租户")
    return context


async def require_platform_admin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    if not user.is_platform_admin:
        raise HTTPException(status_code=403, detail="需要平台管理员权限")
    return user
