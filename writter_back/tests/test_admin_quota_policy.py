"""Platform quota policy request validation tests."""

from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api import tenant_features
from api.routers import admin_router
from api.routers.admin_router import TenantAdminUpdate
from application.feature_policy import FeaturePolicy
from service.entities.identity import CurrentUser


def test_disabling_unlimited_requires_finite_limit():
    with pytest.raises(ValidationError, match="必须同时设置月度额度"):
        TenantAdminUpdate(monthly_generation_unlimited=False)


def test_quota_policy_accepts_explicit_finite_limit():
    update = TenantAdminUpdate(
        monthly_generation_unlimited=False,
        monthly_generation_limit=120,
    )

    assert update.monthly_generation_unlimited is False
    assert update.monthly_generation_limit == 120


def test_enabling_unlimited_does_not_require_limit():
    update = TenantAdminUpdate(monthly_generation_unlimited=True)

    assert update.monthly_generation_unlimited is True
    assert update.monthly_generation_limit is None


def _admin() -> CurrentUser:
    return CurrentUser(
        id=uuid4(), email="admin@example.com", is_platform_admin=True, status="active",
    )


def _policy(global_enabled: bool) -> FeaturePolicy:
    return FeaturePolicy(SimpleNamespace(
        NOVEL_PLANNING_V1_ENABLED=global_enabled,
        WORKFLOW_REVIEW_V3_ENABLED=False,
    ))


@pytest.mark.asyncio
async def test_admin_tenant_list_returns_requested_and_effective_flags(monkeypatch):
    monkeypatch.setattr(tenant_features, "feature_policy", _policy(True))
    identity = SimpleNamespace(admin_list_tenants=AsyncMock(return_value=[{
        "id": str(uuid4()), "novel_planning_v1_enabled": True,
    }]))

    result = await admin_router.tenants(_admin(), identity)

    assert result[0]["novel_planning_v1_enabled"] is True
    assert result[0]["novel_planning_v1_globally_enabled"] is True
    assert result[0]["novel_planning_v1_effective"] is True


@pytest.mark.asyncio
async def test_admin_patch_updates_requested_flag_and_reports_global_kill_switch(monkeypatch):
    monkeypatch.setattr(tenant_features, "feature_policy", _policy(False))
    identity = SimpleNamespace(admin_update_tenant=AsyncMock(return_value=True))
    tenant_id = uuid4()

    result = await admin_router.update_tenant(
        tenant_id, TenantAdminUpdate(novel_planning_v1_enabled=True), _admin(), identity,
    )

    identity.admin_update_tenant.assert_awaited_once_with(
        ANY, tenant_id, {"novel_planning_v1_enabled": True},
    )
    assert result["novel_planning_v1_enabled"] is True
    assert result["novel_planning_v1_globally_enabled"] is False
    assert result["novel_planning_v1_effective"] is False
