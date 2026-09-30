import pytest

from application.research.originality import CopyRiskError, assert_original_summary, find_long_overlaps


def test_long_overlap_is_detected_without_returning_full_source() -> None:
    source = "门外传来三次敲击，随后倒计时开始。"
    generated = "开局先出现门外传来三次敲击，随后倒计时开始。"
    overlaps = find_long_overlaps(source, generated)
    assert overlaps
    assert len(overlaps[0]) == 12


def test_short_common_overlap_is_allowed() -> None:
    assert find_long_overlaps("主角看向门外", "主角看向门外") == ()


def test_copy_risk_blocks_summary() -> None:
    with pytest.raises(CopyRiskError):
        assert_original_summary("异常发生后倒计时开始并且门外出现脚步声", "异常发生后倒计时开始并且门外出现脚步声")
