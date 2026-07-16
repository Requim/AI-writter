from application.agents.reflection_node import _normalize_issues


def test_normalize_issues_accepts_single_object_from_model() -> None:
    issue = {"type": "logic", "severity": "high"}

    assert _normalize_issues(issue) == [issue]


def test_normalize_issues_drops_non_object_items() -> None:
    issue = {"type": "pacing", "severity": "medium"}

    assert _normalize_issues([issue, None, "invalid"]) == [issue]
