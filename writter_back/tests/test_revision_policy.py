import pytest

from application.revision_policy import allow_full_revision_fallback


@pytest.mark.parametrize("values,allowed", [
    ({}, False), ({"auto_mode": False}, False), ({"auto_mode": True}, True),
    ({"direct_rewrite": True}, True),
])
def test_contract_fallback_requires_automatic_or_explicit_rewrite(values, allowed):
    assert allow_full_revision_fallback({"goal_contract": {"id": "fixed"}},
                                       {"configurable": values}) is allowed


def test_legacy_fallback_behavior_is_preserved():
    assert allow_full_revision_fallback({}, {})
