"""Tenant-aware workflow feature policy tests."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from application.errors import PlanningTemporarilyDisabledError
from application.feature_policy import (
    FeaturePolicy,
    planning_v1_enabled_now,
    require_planning_v1,
)
from api.tenant_features import tenant_feature_status
from service.entities.identity import TenantContext


def _context(requested: bool | None = None) -> TenantContext:
    values = {
        "tenant_id": uuid4(),
        "tenant_name": "测试租户",
        "user_id": uuid4(),
        "role": "owner",
        "is_platform_admin": False,
        "ai_enabled": True,
        "monthly_generation_limit": 30,
    }
    if requested is not None:
        values["novel_planning_v1_enabled"] = requested
    return TenantContext(**values)


def _policy(global_enabled: bool, review_enabled: bool = False) -> FeaturePolicy:
    return FeaturePolicy(SimpleNamespace(
        NOVEL_PLANNING_V1_ENABLED=global_enabled,
        WORKFLOW_REVIEW_V3_ENABLED=review_enabled,
    ))


def test_tenant_context_defaults_planning_request_to_false() -> None:
    assert _context().novel_planning_v1_enabled is False


@pytest.mark.parametrize(
    ("global_enabled", "requested", "effective"),
    [(False, False, False), (False, True, False), (True, False, False), (True, True, True)],
)
def test_planning_requires_global_and_tenant_flags(
    global_enabled: bool, requested: bool, effective: bool,
) -> None:
    policy = _policy(global_enabled)

    assert policy.novel_planning_v1_enabled(_context(requested)) is effective
    assert policy.novel_planning_v1_effective(requested) is effective


@pytest.mark.parametrize(
    ("global_enabled", "requested", "review_enabled", "expected"),
    [(True, True, False, 5), (True, False, True, 4), (False, True, True, 4), (False, True, False, 2)],
)
def test_schema_selection_respects_policy_precedence(
    global_enabled: bool, requested: bool, review_enabled: bool, expected: int,
) -> None:
    policy = _policy(global_enabled, review_enabled)

    assert policy.workflow_schema_version(_context(requested)) == expected


def test_public_tenant_summary_exposes_requested_and_effective(monkeypatch) -> None:
    monkeypatch.setattr(
        "application.feature_policy.settings.NOVEL_PLANNING_V1_ENABLED", True
    )
    payload = tenant_feature_status({
        "id": "tenant-1",
        "novel_planning_v1_enabled": True,
    })
    assert payload["novel_planning_v1_enabled"] is True
    assert payload["novel_planning_v1_effective"] is True
    assert payload["novel_planning_v1_globally_enabled"] is True


@pytest.mark.asyncio
async def test_live_tenant_loader_can_stop_a_running_schema_five_workflow() -> None:
    context = _context(True)
    config = {"configurable": {
        "feature_policy": _policy(True),
        "tenant_context": context,
        "novel_planning_v1_enabled": True,
        "tenant_planning_loader": lambda _tenant_id: False,
    }}

    assert await planning_v1_enabled_now(config) is False
    with pytest.raises(
        PlanningTemporarilyDisabledError,
        match="创作现场已保留",
    ):
        await require_planning_v1(config)
