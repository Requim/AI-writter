import pytest

from application.agents.reflection_node import (
    _normalize_issues,
    _validate_reflection_metrics,
)
from application.errors import RetryableWorkflowError


def test_normalize_issues_accepts_single_object_from_model() -> None:
    issue = {"type": "logic", "severity": "high"}

    assert _normalize_issues(issue) == [issue]


def test_normalize_issues_drops_non_object_items() -> None:
    issue = {"type": "pacing", "severity": "medium"}

    assert _normalize_issues([issue, None, "invalid"]) == [issue]


def test_reflection_metrics_accept_numeric_strings_and_percentages() -> None:
    metrics = _validate_reflection_metrics(
        {
            "passed": "true",
            "overall_quality_score": "92%",
            "word_count_analysis": {
                "total_count": "14092",
                "effective_density": "82%",
                "is_valid_word_count": "false",
            },
        }
    )

    assert metrics.passed is True
    assert metrics.overall_quality_score == pytest.approx(0.92)
    assert metrics.word_count_analysis.effective_density == pytest.approx(82)
    assert metrics.word_count_analysis.is_valid_word_count is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("overall_quality_score", "优秀"),
        ("effective_density", "有效内容占比较高"),
        ("is_valid_word_count", "大致合格"),
    ],
)
def test_reflection_metrics_reject_invalid_model_values(
    field: str,
    value: str,
) -> None:
    result = {
        "passed": True,
        "overall_quality_score": 0.92,
        "word_count_analysis": {
            "total_count": 14092,
            "effective_density": 82,
            "is_valid_word_count": True,
        },
    }
    target = result if field == "overall_quality_score" else result["word_count_analysis"]
    target[field] = value

    with pytest.raises(RetryableWorkflowError):
        _validate_reflection_metrics(result)
