"""Create or update the platform administrator and attach the legacy tenant."""

import asyncio
from uuid import UUID

from application.auth_service import AuthService
from config import settings
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.database.repository import PostgresNovelRepository

LEGACY_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")


async def main() -> None:
    if not settings.PLATFORM_ADMIN_EMAIL or not settings.PLATFORM_ADMIN_PASSWORD:
        raise RuntimeError(
            "PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD are required"
        )
    repository = PostgresNovelRepository(settings.DATABASE_URL)
    try:
        identity = IdentityRepository(repository.async_session)
        auth = AuthService(identity, settings)
        email = auth.normalize_email(settings.PLATFORM_ADMIN_EMAIL)
        user = await identity.bootstrap_platform_admin(
            email,
            auth.hash_password(settings.PLATFORM_ADMIN_PASSWORD),
            LEGACY_TENANT_ID,
        )
        print(f"Platform administrator ready: {user.email}")
    finally:
        await repository.aclose()


if __name__ == "__main__":
    asyncio.run(main())
