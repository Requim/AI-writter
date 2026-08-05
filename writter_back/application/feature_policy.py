"""Centralized tenant-aware workflow feature decisions."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from application.errors import PlanningTemporarilyDisabledError
from config import settings
from service.entities.identity import TenantContext


class FeatureSettings(Protocol):
    NOVEL_PLANNING_V1_ENABLED: bool
    WORKFLOW_REVIEW_V3_ENABLED: bool


class FeaturePolicy:
    """Resolve global kill switches together with tenant requests."""

    def __init__(self, settings_source: FeatureSettings) -> None:
        self._settings = settings_source

    @property
    def novel_planning_v1_globally_enabled(self) -> bool:
        return bool(self._settings.NOVEL_PLANNING_V1_ENABLED)

    def novel_planning_v1_effective(self, tenant_requested: bool) -> bool:
        return self.novel_planning_v1_globally_enabled and tenant_requested

    def novel_planning_v1_enabled(self, context: TenantContext) -> bool:
        return self.novel_planning_v1_effective(context.novel_planning_v1_enabled)

    def workflow_schema_version(self, context: TenantContext) -> int:
        if self.novel_planning_v1_enabled(context):
            return 5
        return 4 if self._settings.WORKFLOW_REVIEW_V3_ENABLED else 2


feature_policy = FeaturePolicy(settings)


TenantPlanningLoader = Callable[[Any], bool | Awaitable[bool]]


async def planning_v1_enabled_now(config: Mapping[str, Any]) -> bool:
    """Resolve the live tenant flag through dependencies injected by the workflow."""
    values = config.get("configurable", {})
    policy = values.get("feature_policy")
    context = values.get("tenant_context")
    if not isinstance(policy, FeaturePolicy) or not isinstance(context, TenantContext):
        return bool(values.get("novel_planning_v1_enabled", False))
    requested = context.novel_planning_v1_enabled
    loader = values.get("tenant_planning_loader")
    if callable(loader):
        loaded = loader(context.tenant_id)
        requested = bool(await loaded) if inspect.isawaitable(loaded) else bool(loaded)
    return policy.novel_planning_v1_effective(requested)


async def require_planning_v1(
    config: Mapping[str, Any], *, workflow_schema_version: int = 5
) -> None:
    if workflow_schema_version < 5:
        return
    if not await planning_v1_enabled_now(config):
        raise PlanningTemporarilyDisabledError(
            "整书规划当前已暂停，创作现场已保留，请在功能恢复后继续"
        )
