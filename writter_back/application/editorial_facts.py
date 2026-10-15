"""Conservative literal copyediting checks independent of model scores."""

import re

_TEXT = r"[\u4e00-\u9fff，、；： \t]{1,80}"
_COUNT = r"[零〇一二两三四五六七八九十]{1,3}|[0-9]{1,2}"
_NOTE_COUNTS = (re.compile(
    r"(?:写下|写道|记下|写)[：:][ \t]*"
    rf"(?P<text>{_TEXT})。\s*(?P<count>{_COUNT})个字。"
), re.compile(rf"只有(?P<count>{_COUNT})个字[：:][ \t]*(?P<text>{_TEXT})。"))
_DIGITS = {char: value for value, char in enumerate("零一二三四五六七八九")}
_DIGITS.update({"〇": 0, "两": 2})


def _count_number(text: str) -> int | None:
    if text.isascii() and text.isdecimal():
        return int(text)
    if text in _DIGITS:
        return _DIGITS[text]
    if text.count("十") != 1:
        return None
    left, right = text.split("十")
    if ((left and left not in _DIGITS) or (right and right not in _DIGITS)):
        return None
    return _DIGITS.get(left, 1) * 10 + _DIGITS.get(right, 0)


def literal_count_issues(content: str) -> list[dict]:
    """Only count adjacent, explicit Han-only notes outside quoted dialogue."""
    issues = []
    for match in (match for pattern in _NOTE_COUNTS for match in pattern.finditer(content)):
        start = content.rfind("\n\n", 0, match.start())
        prefix = content[start + 2 if start >= 0 else 0:match.start()]
        if any(mark in prefix for mark in ('"', "'", "“", "”", "‘", "’")):
            continue
        stated = _count_number(match["count"])
        actual = sum("\u4e00" <= char <= "\u9fff" for char in match["text"])
        if stated is None or stated == actual:
            continue
        issues.append({
            "type": "continuity", "severity": "high", "priority_action": "must_fix",
            "source": "server_text_count", "evidence": match.group(),
            "location": f"字符 {match.start()}",
            "description": f"紧邻明确写下的文本实际有 {actual} 个汉字，旁白却称 {stated} 个字。",
            "suggestion": "纠正该处计数或删除不必要的计数旁白，不改写记录内容和情节。",
        })
    return issues
