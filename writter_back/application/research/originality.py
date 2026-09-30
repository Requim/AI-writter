"""研究摘要的原文重合检查；不保存输入文本。"""

from __future__ import annotations

import re


class CopyRiskError(ValueError):
    """摘要包含过长的连续原文重合。"""


def _compact(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", text).lower()


def find_long_overlaps(source: str, generated: str, minimum_run: int = 12) -> tuple[str, ...]:
    """返回需要阻断的连续重合片段，不返回原始文本之外的内容。"""
    if minimum_run < 1:
        raise ValueError("重合阈值必须大于零")
    source_compact, generated_compact = _compact(source), _compact(generated)
    matches = {
        generated_compact[index:index + minimum_run]
        for index in range(max(0, len(generated_compact) - minimum_run + 1))
        if generated_compact[index:index + minimum_run] in source_compact
    }
    return tuple(sorted(matches))


def assert_original_summary(source: str, generated: str, minimum_run: int = 12) -> None:
    """模型摘要命中连续原文时失败，调用方应丢弃本次结果。"""
    overlaps = find_long_overlaps(source, generated, minimum_run)
    if overlaps:
        raise CopyRiskError("研究摘要包含连续原文重合，不能进入结果集")
