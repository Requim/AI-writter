import json

import pytest

from application.prose_output import strip_trailing_goal_report


REPORT = json.dumps({"goal_checks": [
    {"id": "ch5:must:1", "status": "passed", "evidence": "他合上卷宗。",
     "reason": "事件已发生"}
]}, ensure_ascii=False)


@pytest.mark.parametrize("suffix", [REPORT, "```json\n" + REPORT + "\n```"])
def test_only_trailing_machine_report_is_removed(suffix):
    prose = "他合上卷宗。\n窗外的脚步停了。"
    assert strip_trailing_goal_report(prose + "\n\n" + suffix) == prose


@pytest.mark.parametrize("text", [
    '他读到 {"key": "value"}，关上屏幕。',
    '他读到 {"goal_checks": []}',
    REPORT,
    "正文\n" + REPORT + "\n之后他回了家。",
    "正文\n{\"goal_checks\":",
    '正文\n{"goal_checks":[{"id":"a","status":[],"evidence":"","reason":""}]}',
])
def test_story_json_incomplete_output_and_report_only_are_preserved(text):
    assert strip_trailing_goal_report(text) == text
