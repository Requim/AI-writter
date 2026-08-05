"""Public tenant feature status presentation."""

from typing import Any

from application.feature_policy import feature_policy


def tenant_feature_status(tenant: dict[str, Any]) -> dict[str, Any]:
    result = dict(tenant)
    requested = bool(result.get("novel_planning_v1_enabled", False))
    result.update(
        novel_planning_v1_enabled=requested,
        novel_planning_v1_effective=(
            feature_policy.novel_planning_v1_effective(requested)
        ),
        novel_planning_v1_globally_enabled=(
            feature_policy.novel_planning_v1_globally_enabled
        ),
    )
    return result


def tenant_feature_list(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tenant_feature_status(row) for row in rows]
