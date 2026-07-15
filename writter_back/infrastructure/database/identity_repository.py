"""Persistence operations for users, tenants, sessions, invitations and quota."""

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.models import (
    AuditEventModel,
    QuotaLedgerModel,
    RefreshSessionModel,
    TenantInvitationModel,
    TenantMembershipModel,
    TenantModel,
    UserModel,
)
from service.entities.identity import CurrentUser, TenantContext


class DuplicateIdentityError(ValueError):
    pass


class QuotaExceededError(RuntimeError):
    pass


class AIUnavailableError(RuntimeError):
    pass


class IdentityRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    async def register(
        self,
        email: str,
        password_hash: str,
        tenant_name: str,
        tenant_slug: str,
        monthly_limit: int,
    ) -> tuple[UserModel, TenantModel]:
        user = UserModel(email=email, password_hash=password_hash)
        tenant = TenantModel(
            name=tenant_name,
            slug=tenant_slug,
            monthly_generation_limit=monthly_limit,
        )
        try:
            async with self.session_factory() as session, session.begin():
                session.add_all([user, tenant])
                await session.flush()
                session.add(
                    TenantMembershipModel(tenant_id=tenant.id, user_id=user.id, role="owner")
                )
                session.add(
                    AuditEventModel(
                        tenant_id=tenant.id,
                        actor_user_id=user.id,
                        action="tenant.registered",
                        target_type="tenant",
                        target_id=str(tenant.id),
                    )
                )
        except IntegrityError as exc:
            raise DuplicateIdentityError("邮箱或租户标识已存在") from exc
        return user, tenant

    async def find_user_by_email(self, email: str) -> UserModel | None:
        async with self.session_factory() as session:
            return (
                await session.execute(select(UserModel).where(UserModel.email == email))
            ).scalar_one_or_none()

    async def find_user_by_id(self, user_id: UUID) -> UserModel | None:
        async with self.session_factory() as session:
            return await session.get(UserModel, user_id)

    async def current_user(self, user_id: UUID) -> CurrentUser | None:
        user = await self.find_user_by_id(user_id)
        if user is None:
            return None
        return CurrentUser(
            id=user.id,
            email=user.email,
            is_platform_admin=user.is_platform_admin,
            status=user.status,
        )

    async def list_tenants(self, user_id: UUID) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(TenantModel, TenantMembershipModel.role)
                    .join(
                        TenantMembershipModel,
                        TenantMembershipModel.tenant_id == TenantModel.id,
                    )
                    .where(TenantMembershipModel.user_id == user_id)
                    .order_by(TenantModel.created_at)
                )
            ).all()
            return [
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "role": role,
                    "status": tenant.status,
                    "ai_enabled": tenant.ai_enabled,
                    "monthly_generation_limit": tenant.monthly_generation_limit,
                }
                for tenant, role in rows
            ]

    async def get_tenant_context(self, user: CurrentUser, tenant_id: UUID) -> TenantContext | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(TenantModel, TenantMembershipModel.role)
                    .join(
                        TenantMembershipModel,
                        TenantMembershipModel.tenant_id == TenantModel.id,
                    )
                    .where(
                        TenantModel.id == tenant_id,
                        TenantMembershipModel.user_id == user.id,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            tenant, role = row
            if tenant.status != "active":
                return None
            return TenantContext(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                user_id=user.id,
                role=role,
                is_platform_admin=user.is_platform_admin,
                ai_enabled=tenant.ai_enabled,
                monthly_generation_limit=tenant.monthly_generation_limit,
            )

    async def create_refresh_session(
        self, user_id: UUID, token_hash: str, expires_at: datetime
    ) -> None:
        async with self.session_factory() as session, session.begin():
            session.add(
                RefreshSessionModel(
                    user_id=user_id,
                    token_hash=token_hash,
                    expires_at=expires_at,
                )
            )

    async def rotate_refresh_session(
        self,
        old_hash: str,
        new_hash: str,
        new_expires_at: datetime,
    ) -> UserModel | None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session, session.begin():
            old = (
                await session.execute(
                    select(RefreshSessionModel)
                    .where(RefreshSessionModel.token_hash == old_hash)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if old is None or old.revoked_at is not None or old.expires_at <= now:
                return None
            user = await session.get(UserModel, old.user_id)
            if user is None or user.status != "active":
                return None
            old.revoked_at = now
            old.last_used_at = now
            session.add(
                RefreshSessionModel(
                    user_id=user.id,
                    token_hash=new_hash,
                    expires_at=new_expires_at,
                )
            )
            return user

    async def revoke_refresh_session(self, token_hash: str) -> None:
        async with self.session_factory() as session, session.begin():
            item = (
                await session.execute(
                    select(RefreshSessionModel).where(
                        RefreshSessionModel.token_hash == token_hash
                    )
                )
            ).scalar_one_or_none()
            if item is not None and item.revoked_at is None:
                item.revoked_at = datetime.now(timezone.utc)

    async def change_password(self, user_id: UUID, password_hash: str) -> None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session, session.begin():
            user = await session.get(UserModel, user_id)
            if user is None:
                raise ValueError("账号不存在")
            user.password_hash = password_hash
            sessions = (
                await session.execute(
                    select(RefreshSessionModel).where(
                        RefreshSessionModel.user_id == user_id,
                        RefreshSessionModel.revoked_at.is_(None),
                    )
                )
            ).scalars()
            for item in sessions:
                item.revoked_at = now

    async def create_invitation(
        self,
        context: TenantContext,
        token_hash: str,
        role: str,
        expires_at: datetime,
    ) -> TenantInvitationModel:
        invitation = TenantInvitationModel(
            tenant_id=context.tenant_id,
            created_by_user_id=context.user_id,
            token_hash=token_hash,
            role=role,
            expires_at=expires_at,
        )
        async with self.session_factory() as session, session.begin():
            session.add(invitation)
            await session.flush()
            session.add(
                AuditEventModel(
                    tenant_id=context.tenant_id,
                    actor_user_id=context.user_id,
                    action="membership.invited",
                    target_type="invitation",
                    target_id=str(invitation.id),
                    details={"role": role},
                )
            )
        return invitation

    async def accept_invitation(self, token_hash: str, user_id: UUID) -> UUID | None:
        now = datetime.now(timezone.utc)
        async with self.session_factory() as session, session.begin():
            invite = (
                await session.execute(
                    select(TenantInvitationModel)
                    .where(TenantInvitationModel.token_hash == token_hash)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                invite is None
                or invite.accepted_at is not None
                or invite.expires_at <= now
            ):
                return None
            membership = await session.get(
                TenantMembershipModel,
                {"tenant_id": invite.tenant_id, "user_id": user_id},
            )
            if membership is None:
                session.add(
                    TenantMembershipModel(
                        tenant_id=invite.tenant_id,
                        user_id=user_id,
                        role=invite.role,
                    )
                )
            invite.accepted_at = now
            invite.accepted_by_user_id = user_id
            session.add(
                AuditEventModel(
                    tenant_id=invite.tenant_id,
                    actor_user_id=user_id,
                    action="membership.joined",
                    target_type="user",
                    target_id=str(user_id),
                )
            )
            return invite.tenant_id

    async def list_members(self, tenant_id: UUID) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(UserModel, TenantMembershipModel.role, TenantMembershipModel.created_at)
                    .join(UserModel, UserModel.id == TenantMembershipModel.user_id)
                    .where(TenantMembershipModel.tenant_id == tenant_id)
                    .order_by(TenantMembershipModel.created_at)
                )
            ).all()
            return [
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "role": role,
                    "status": user.status,
                    "joined_at": joined_at,
                }
                for user, role, joined_at in rows
            ]

    async def update_member_role(
        self, context: TenantContext, user_id: UUID, role: str
    ) -> bool:
        async with self.session_factory() as session, session.begin():
            membership = await session.get(
                TenantMembershipModel,
                {"tenant_id": context.tenant_id, "user_id": user_id},
            )
            if membership is None or membership.role == "owner":
                return False
            membership.role = role
            session.add(
                AuditEventModel(
                    tenant_id=context.tenant_id,
                    actor_user_id=context.user_id,
                    action="membership.role_changed",
                    target_type="user",
                    target_id=str(user_id),
                    details={"role": role},
                )
            )
            return True

    async def remove_member(self, context: TenantContext, user_id: UUID) -> bool:
        async with self.session_factory() as session, session.begin():
            membership = await session.get(
                TenantMembershipModel,
                {"tenant_id": context.tenant_id, "user_id": user_id},
            )
            if (
                membership is None
                or membership.role == "owner"
                or (context.role == "admin" and membership.role != "member")
            ):
                return False
            await session.delete(membership)
            session.add(
                AuditEventModel(
                    tenant_id=context.tenant_id,
                    actor_user_id=context.user_id,
                    action="membership.removed",
                    target_type="user",
                    target_id=str(user_id),
                )
            )
            return True

    async def transfer_ownership(
        self, context: TenantContext, target_user_id: UUID
    ) -> bool:
        async with self.session_factory() as session, session.begin():
            current = await session.get(
                TenantMembershipModel,
                {"tenant_id": context.tenant_id, "user_id": context.user_id},
            )
            target = await session.get(
                TenantMembershipModel,
                {"tenant_id": context.tenant_id, "user_id": target_user_id},
            )
            if current is None or current.role != "owner" or target is None:
                return False
            current.role = "admin"
            target.role = "owner"
            session.add(
                AuditEventModel(
                    tenant_id=context.tenant_id,
                    actor_user_id=context.user_id,
                    action="tenant.ownership_transferred",
                    target_type="user",
                    target_id=str(target_user_id),
                )
            )
            return True

    async def reserve_quota(
        self,
        context: TenantContext,
        workflow_run_id: UUID,
        operation_type: str,
        chapter_index: int,
        period_start: date,
    ) -> tuple[int, int]:
        async with self.session_factory() as session, session.begin():
            tenant = (
                await session.execute(
                    select(TenantModel)
                    .where(TenantModel.id == context.tenant_id)
                    .with_for_update()
                )
            ).scalar_one()
            if tenant.status != "active" or not tenant.ai_enabled:
                raise AIUnavailableError("该租户的 AI 创作功能当前不可用")
            existing = (
                await session.execute(
                    select(QuotaLedgerModel.id).where(
                        QuotaLedgerModel.tenant_id == context.tenant_id,
                        QuotaLedgerModel.workflow_run_id == workflow_run_id,
                        QuotaLedgerModel.operation_type == operation_type,
                        QuotaLedgerModel.chapter_index == chapter_index,
                    )
                )
            ).scalar_one_or_none()
            used = int(
                (
                    await session.execute(
                        select(func.count(QuotaLedgerModel.id)).where(
                            QuotaLedgerModel.tenant_id == context.tenant_id,
                            QuotaLedgerModel.period_start == period_start,
                        )
                    )
                ).scalar_one()
            )
            if existing is not None:
                return used, tenant.monthly_generation_limit
            if used >= tenant.monthly_generation_limit:
                raise QuotaExceededError("本月 AI 创作额度已用完")
            session.add(
                QuotaLedgerModel(
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    workflow_run_id=workflow_run_id,
                    operation_type=operation_type,
                    chapter_index=chapter_index,
                    period_start=period_start,
                )
            )
            return used + 1, tenant.monthly_generation_limit

    async def quota_usage(self, tenant_id: UUID, period_start: date) -> int:
        async with self.session_factory() as session:
            return int(
                (
                    await session.execute(
                        select(func.count(QuotaLedgerModel.id)).where(
                            QuotaLedgerModel.tenant_id == tenant_id,
                            QuotaLedgerModel.period_start == period_start,
                        )
                    )
                ).scalar_one()
            )

    async def admin_list_tenants(self, period_start: date) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            member_count = (
                select(
                    TenantMembershipModel.tenant_id,
                    func.count().label("member_count"),
                )
                .group_by(TenantMembershipModel.tenant_id)
                .subquery()
            )
            usage = (
                select(
                    QuotaLedgerModel.tenant_id,
                    func.count().label("usage"),
                )
                .where(QuotaLedgerModel.period_start == period_start)
                .group_by(QuotaLedgerModel.tenant_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(
                        TenantModel,
                        func.coalesce(member_count.c.member_count, 0),
                        func.coalesce(usage.c.usage, 0),
                    )
                    .outerjoin(member_count, member_count.c.tenant_id == TenantModel.id)
                    .outerjoin(usage, usage.c.tenant_id == TenantModel.id)
                    .order_by(TenantModel.created_at.desc())
                )
            ).all()
            return [
                {
                    "id": str(tenant.id),
                    "name": tenant.name,
                    "slug": tenant.slug,
                    "status": tenant.status,
                    "ai_enabled": tenant.ai_enabled,
                    "monthly_generation_limit": tenant.monthly_generation_limit,
                    "member_count": members,
                    "usage": used,
                }
                for tenant, members, used in rows
            ]

    async def admin_list_users(self) -> list[dict[str, Any]]:
        async with self.session_factory() as session:
            membership_count = (
                select(
                    TenantMembershipModel.user_id,
                    func.count().label("tenant_count"),
                )
                .group_by(TenantMembershipModel.user_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(
                        UserModel,
                        func.coalesce(membership_count.c.tenant_count, 0),
                    )
                    .outerjoin(
                        membership_count,
                        membership_count.c.user_id == UserModel.id,
                    )
                    .order_by(UserModel.created_at.desc())
                )
            ).all()
            return [
                {
                    "id": str(user.id),
                    "email": user.email,
                    "status": user.status,
                    "is_platform_admin": user.is_platform_admin,
                    "tenant_count": tenant_count,
                    "created_at": user.created_at,
                }
                for user, tenant_count in rows
            ]

    async def admin_update_tenant(
        self,
        actor_user_id: UUID,
        tenant_id: UUID,
        values: dict[str, Any],
    ) -> bool:
        async with self.session_factory() as session, session.begin():
            tenant = await session.get(TenantModel, tenant_id)
            if tenant is None:
                return False
            for key, value in values.items():
                setattr(tenant, key, value)
            session.add(
                AuditEventModel(
                    tenant_id=tenant_id,
                    actor_user_id=actor_user_id,
                    action="tenant.admin_updated",
                    target_type="tenant",
                    target_id=str(tenant_id),
                    details=values,
                )
            )
            return True

    async def admin_update_user_status(self, user_id: UUID, status: str) -> bool:
        async with self.session_factory() as session, session.begin():
            user = await session.get(UserModel, user_id)
            if user is None:
                return False
            user.status = status
            return True

    async def bootstrap_platform_admin(
        self,
        email: str,
        password_hash: str,
        legacy_tenant_id: UUID,
    ) -> UserModel:
        async with self.session_factory() as session, session.begin():
            user = (
                await session.execute(select(UserModel).where(UserModel.email == email))
            ).scalar_one_or_none()
            if user is None:
                user = UserModel(
                    email=email,
                    password_hash=password_hash,
                    is_platform_admin=True,
                )
                session.add(user)
                await session.flush()
            else:
                user.password_hash = password_hash
                user.is_platform_admin = True
                user.status = "active"
            tenant = await session.get(TenantModel, legacy_tenant_id)
            if tenant is not None:
                membership = await session.get(
                    TenantMembershipModel,
                    {"tenant_id": legacy_tenant_id, "user_id": user.id},
                )
                if membership is None:
                    session.add(
                        TenantMembershipModel(
                            tenant_id=legacy_tenant_id,
                            user_id=user.id,
                            role="owner",
                        )
                    )
            return user
