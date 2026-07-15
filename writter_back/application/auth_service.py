"""Password, JWT and refresh-token lifecycle for public authentication."""

from datetime import datetime, timedelta, timezone
import hashlib
import re
import secrets
from typing import Any
from uuid import UUID, uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
import jwt
from jwt import InvalidTokenError

from config import Settings
from infrastructure.database.identity_repository import (
    DuplicateIdentityError,
    IdentityRepository,
)
from infrastructure.database.models import UserModel

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthenticationError(ValueError):
    pass


class AuthService:
    def __init__(self, repository: IdentityRepository, config: Settings):
        if len(config.JWT_SECRET) < 32:
            raise RuntimeError("JWT_SECRET must contain at least 32 characters")
        self.repository = repository
        self.config = config
        self.password_hasher = PasswordHasher()

    @staticmethod
    def normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if len(normalized) > 320 or not EMAIL_RE.fullmatch(normalized):
            raise ValueError("邮箱格式不正确")
        return normalized

    @staticmethod
    def validate_password(password: str) -> None:
        if len(password) < 10 or len(password) > 256:
            raise ValueError("密码长度必须为 10 到 256 个字符")

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _slug(name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:72]
        return f"{base or 'tenant'}-{uuid4().hex[:8]}"

    def hash_password(self, password: str) -> str:
        self.validate_password(password)
        return self.password_hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return self.password_hasher.verify(password_hash, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def issue_access_token(self, user: UserModel) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        lifetime = timedelta(minutes=self.config.ACCESS_TOKEN_MINUTES)
        payload = {
            "sub": str(user.id),
            "jti": uuid4().hex,
            "type": "access",
            "iat": now,
            "exp": now + lifetime,
            "iss": self.config.JWT_ISSUER,
            "aud": self.config.JWT_AUDIENCE,
        }
        token = jwt.encode(payload, self.config.JWT_SECRET, algorithm="HS256")
        return token, int(lifetime.total_seconds())

    def decode_access_token(self, token: str) -> UUID:
        try:
            payload: dict[str, Any] = jwt.decode(
                token,
                self.config.JWT_SECRET,
                algorithms=["HS256"],
                issuer=self.config.JWT_ISSUER,
                audience=self.config.JWT_AUDIENCE,
            )
            if payload.get("type") != "access":
                raise AuthenticationError("令牌类型不正确")
            return UUID(payload["sub"])
        except (InvalidTokenError, KeyError, ValueError) as exc:
            raise AuthenticationError("登录状态无效或已过期") from exc

    async def _new_token_pair(self, user: UserModel) -> dict[str, Any]:
        access_token, expires_in = self.issue_access_token(user)
        refresh_token = secrets.token_urlsafe(48)
        refresh_expires = datetime.now(timezone.utc) + timedelta(
            days=self.config.REFRESH_TOKEN_DAYS
        )
        await self.repository.create_refresh_session(
            user.id,
            self.token_hash(refresh_token),
            refresh_expires,
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    async def register(
        self, email: str, password: str, tenant_name: str
    ) -> tuple[UserModel, dict[str, Any]]:
        normalized_email = self.normalize_email(email)
        clean_name = tenant_name.strip()
        if not 2 <= len(clean_name) <= 120:
            raise ValueError("工作区名称长度必须为 2 到 120 个字符")
        user, _tenant = await self.repository.register(
            normalized_email,
            self.hash_password(password),
            clean_name,
            self._slug(clean_name),
            self.config.DEFAULT_MONTHLY_GENERATION_LIMIT,
        )
        return user, await self._new_token_pair(user)

    async def login(self, email: str, password: str) -> tuple[UserModel, dict[str, Any]]:
        normalized_email = self.normalize_email(email)
        user = await self.repository.find_user_by_email(normalized_email)
        if (
            user is None
            or user.status != "active"
            or not self.verify_password(user.password_hash, password)
        ):
            raise AuthenticationError("邮箱或密码不正确")
        return user, await self._new_token_pair(user)

    async def refresh(self, refresh_token: str) -> tuple[UserModel, dict[str, Any]]:
        new_refresh = secrets.token_urlsafe(48)
        refresh_expires = datetime.now(timezone.utc) + timedelta(
            days=self.config.REFRESH_TOKEN_DAYS
        )
        user = await self.repository.rotate_refresh_session(
            self.token_hash(refresh_token),
            self.token_hash(new_refresh),
            refresh_expires,
        )
        if user is None:
            raise AuthenticationError("刷新令牌无效或已撤销")
        access_token, expires_in = self.issue_access_token(user)
        return user, {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    async def logout(self, refresh_token: str) -> None:
        await self.repository.revoke_refresh_session(self.token_hash(refresh_token))


__all__ = ["AuthService", "AuthenticationError", "DuplicateIdentityError"]
