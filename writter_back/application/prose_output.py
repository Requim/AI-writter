"""Separate an explicitly structured trailing review from generated fiction."""

import json


def strip_trailing_goal_report(content: str) -> str:
    """仅移除末尾完整目标报告，保留小说正文及普通故事内 JSON。"""
    decoder = json.JSONDecoder()
    for start, char in enumerate(content):
        if char != "{" or not content[:start].strip():
            continue
        try:
            value, end = decoder.raw_decode(content[start:])
        except ValueError:
            continue
        tail = content[start + end:].strip()
        if tail not in {"", "```"} or not _is_goal_report(value):
            continue
        prefix = content[:start].rstrip()
        if prefix.endswith("```json"):
            prefix = prefix[:-7].rstrip()
        elif prefix.endswith("```"):
            prefix = prefix[:-3].rstrip()
        return prefix
    return content


def _is_goal_report(value: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"goal_checks"}:
        return False
    rows = value["goal_checks"]
    return isinstance(rows, list) and bool(rows) and all(
        isinstance(row, dict)
        and isinstance(row.get("id"), str)
        and isinstance(row.get("status"), str)
        and row.get("status") in {"passed", "failed", "unknown"}
        and isinstance(row.get("evidence"), str)
        and isinstance(row.get("reason"), str)
        for row in rows
    )
