"""Public account registration and bearer-token lifecycle."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import (
    get_auth_service,
    get_current_user,
    get_identity_repository,
)
from application.auth_service import AuthService, AuthenticationError
from infrastructure.database.identity_repository import (
    DuplicateIdentityError,
    IdentityRepository,
)
from service.entities.identity import CurrentUser

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str
    tenant_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _user_payload(user: Any) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "is_platform_admin": bool(user.is_platform_admin),
        "status": user.status,
    }


async def _session_response(
    user: Any,
    tokens: dict[str, Any],
    identity: IdentityRepository,
) -> dict[str, Any]:
    return {
        **tokens,
        "user": _user_payload(user),
        "tenants": await identity.list_tenants(user.id),
    }


@router.post("/register", status_code=201)
async def register(
    request: RegisterRequest,
    auth: AuthService = Depends(get_auth_service),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    try:
        user, tokens = await auth.register(
            request.email, request.password, request.tenant_name
        )
    except (ValueError, DuplicateIdentityError) as exc:
        raise HTTPException(status_code=409 if isinstance(exc, DuplicateIdentityError) else 422, detail=str(exc)) from exc
    return await _session_response(user, tokens, identity)


@router.post("/login")
async def login(
    request: LoginRequest,
    auth: AuthService = Depends(get_auth_service),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    try:
        user, tokens = await auth.login(request.email, request.password)
    except (AuthenticationError, ValueError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return await _session_response(user, tokens, identity)


@router.post("/refresh")
async def refresh(
    request: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    try:
        user, tokens = await auth.refresh(request.refresh_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return await _session_response(user, tokens, identity)


@router.post("/logout", status_code=204)
async def logout(
    request: RefreshRequest,
    auth: AuthService = Depends(get_auth_service),
) -> None:
    await auth.logout(request.refresh_token)


@router.get("/me")
async def me(
    user: CurrentUser = Depends(get_current_user),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> dict[str, Any]:
    return {
        "user": _user_payload(user),
        "tenants": await identity.list_tenants(user.id),
    }


@router.post("/change-password", status_code=204)
async def change_password(
    request: ChangePasswordRequest,
    user: CurrentUser = Depends(get_current_user),
    auth: AuthService = Depends(get_auth_service),
    identity: IdentityRepository = Depends(get_identity_repository),
) -> None:
    model = await identity.find_user_by_id(user.id)
    if model is None or not auth.verify_password(
        model.password_hash, request.current_password
    ):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    await identity.change_password(user.id, auth.hash_password(request.new_password))
