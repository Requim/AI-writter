"""Read-only budget diagnostics for blocked autonomous checkpoints."""

from application.creative.runtime import budget_bucket
from service.value_objects.creative_budget import budget_capacity


async def checkpoint_budget_blocker(values: dict, config: dict, blocked_node: str | None) -> dict | None:
    if not blocked_node or values.get("author_mode") != "autonomous_v1":
        return None
    scope = config["configurable"]
    repository = scope.get("creative_repository")
    if repository is None:
        return None
    session = await repository.get_session(scope["tenant_id"], scope["novel_id"])
    if not session or session["id"] != values.get("creative_session_id"):
        return None
    bucket = budget_bucket(blocked_node, values)
    used = session["counters"].get(bucket, 0)
    remaining = budget_capacity(session["limits"], session["counters"], bucket)
    if remaining:
        return None
    limit = used
    return {
        "code": "budget_exhausted", "node": blocked_node, "retryable": False,
        "bucket": bucket, "used": used, "limit": limit,
        "message": f"{bucket} 调用预算已耗尽（{used}/{limit}）；草稿和进度已保留，重试不会恢复请求额度。",
    }


def budget_pause_interrupts(interrupts: list, blocker: dict | None) -> list:
    if blocker is None:
        return interrupts
    details = {key: blocker[key] for key in ("retryable", "message", "bucket", "used", "limit")}
    return [
        {**item, **details} if isinstance(item, dict)
        and item.get("action") == "creative_paused" and item.get("reason") == "budget_exhausted"
        else item for item in interrupts
    ]
