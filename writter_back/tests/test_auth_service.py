"""Authentication contract tests without a database or network."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from application.auth_service import AuthenticationError, AuthService
from config import Settings


class FakeIdentityRepository:
    def __init__(self):
        self.users = {}
        self.sessions = {}

    async def register(self, email, password_hash, tenant_name, tenant_slug, monthly_limit):
        user = SimpleNamespace(
            id=uuid4(),
            email=email,
            password_hash=password_hash,
            is_platform_admin=False,
            status="active",
        )
        tenant = SimpleNamespace(id=uuid4(), name=tenant_name, slug=tenant_slug)
        self.users[email] = user
        return user, tenant

    async def find_user_by_email(self, email):
        return self.users.get(email)

    async def create_refresh_session(self, user_id, token_hash, expires_at):
        self.sessions[token_hash] = {"user_id": user_id, "revoked": False}

    async def rotate_refresh_session(self, old_hash, new_hash, new_expires_at):
        session = self.sessions.get(old_hash)
        if not session or session["revoked"]:
            return None
        session["revoked"] = True
        user = next(user for user in self.users.values() if user.id == session["user_id"])
        self.sessions[new_hash] = {"user_id": user.id, "revoked": False}
        return user

    async def revoke_refresh_session(self, token_hash):
        if token_hash in self.sessions:
            self.sessions[token_hash]["revoked"] = True


@pytest.fixture
def auth_service():
    repository = FakeIdentityRepository()
    config = Settings(
        ENVIRONMENT="test",
        JWT_SECRET="t" * 48,
        ACCESS_TOKEN_MINUTES=15,
        REFRESH_TOKEN_DAYS=30,
    )
    return AuthService(repository, config), repository


@pytest.mark.asyncio
async def test_register_login_refresh_and_revoke(auth_service):
    auth, repository = auth_service
    user, registered = await auth.register(
        "Editor@Example.COM",
        "a-secure-password",
        "北岸编辑部",
    )
    assert user.email == "editor@example.com"
    assert auth.decode_access_token(registered["access_token"]) == user.id

    _user, logged_in = await auth.login("editor@example.com", "a-secure-password")
    _user, refreshed = await auth.refresh(logged_in["refresh_token"])
    assert refreshed["refresh_token"] != logged_in["refresh_token"]
    with pytest.raises(AuthenticationError):
        await auth.refresh(logged_in["refresh_token"])

    await auth.logout(refreshed["refresh_token"])
    assert repository.sessions[auth.token_hash(refreshed["refresh_token"])]["revoked"] is True


@pytest.mark.asyncio
async def test_rejects_invalid_password_and_short_password(auth_service):
    auth, _repository = auth_service
    with pytest.raises(ValueError, match="10"):
        await auth.register("editor@example.com", "short", "北岸编辑部")
    await auth.register("editor@example.com", "a-secure-password", "北岸编辑部")
    with pytest.raises(AuthenticationError):
        await auth.login("editor@example.com", "wrong-password")
