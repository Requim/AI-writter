"""Respect manual scope choices while allowing bounded automatic repair."""


def allow_full_revision_fallback(outline: dict, config: dict) -> bool:
    """自动创作或显式整章重写可回退全文修订，固定目标仍由后续门禁校验。"""
    values = config.get("configurable") or {}
    return (
        not outline.get("goal_contract")
        or bool(values.get("auto_mode"))
        or bool(values.get("direct_rewrite"))
    )
