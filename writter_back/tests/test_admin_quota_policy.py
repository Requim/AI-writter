"""Platform quota policy request validation tests."""

import pytest
from pydantic import ValidationError

from api.routers.admin_router import TenantAdminUpdate


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
