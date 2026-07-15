"""Identity and tenant context types used at application boundaries."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

TenantRole = Literal["owner", "admin", "member"]


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    email: str
    is_platform_admin: bool
    status: str


@dataclass(frozen=True)
class TenantContext:
    tenant_id: UUID
    tenant_name: str
    user_id: UUID
    role: TenantRole
    is_platform_admin: bool
    ai_enabled: bool
    monthly_generation_limit: int

    def can_delete_content(self) -> bool:
        return self.role in {"owner", "admin"}

    def can_manage_members(self) -> bool:
        return self.role in {"owner", "admin"}
