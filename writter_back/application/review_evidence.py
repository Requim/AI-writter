"""Repair citation formatting without rewriting prose or overriding goal decisions."""

import json
from typing import Any

from application.prompts.template_loader import render_prompt
from application.source_spans import source_catalog as _source_catalog


def _resolved_candidate(row: dict, catalog: list[dict], content: str) -> dict | None:
    quote = row.get("evidence")
    if isinstance(quote, str) and quote.strip() and quote in content:
        return row
    start, end = row.get("evidence_start"), row.get("evidence_end")
    if not isinstance(start, str) or not isinstance(end, str):
        return row if row.get("status") in {"failed", "unknown"} else None
    index = {item["id"]: item for item in catalog}
    first, last = index.get(start), index.get(end)
    if first is None or last is None or first["start"] > last["start"]:
        return None
    return {key: row.get(key) for key in ("id", "status", "reason")} | {
        "evidence": content[first["start"]:last["end"]]}


async def repair_goal_quotes(
    llm: Any, result: dict, content: str, contract: dict | None,
) -> dict:
    """只纠正已判通过但引用失效的目标证据，复验仍由原目标门禁执行。"""
    if not contract:
        return result
    rows = result.get("goal_checks")
    if not isinstance(rows, list):
        return result
    invalid = [row for row in rows if isinstance(row, dict) and row.get("status") == "passed"
               and (not isinstance(row.get("evidence"), str)
                    or not row["evidence"].strip() or row["evidence"] not in content)]
    if not invalid:
        return result
    ids = {row.get("id") for row in invalid if isinstance(row.get("id"), str)}
    requirements = [row for row in contract.get("requirements", []) if row.get("id") in ids]
    catalog = _source_catalog(content)
    prompt = render_prompt(
        "reflection/repair_goal_evidence_v2.txt", include_active_rules=False,
        requirements=json.dumps(requirements, ensure_ascii=False),
        invalid=json.dumps(invalid, ensure_ascii=False), content=content,
        catalog=json.dumps([{"id": item["id"], "text": item["text"]} for item in catalog], ensure_ascii=False),
    )
    repaired = await llm.structured_generate(
        prompt, {"goal_checks": "array"}, temperature=0.1, max_attempts=1,
    )
    candidates = repaired.get("goal_checks", []) if isinstance(repaired, dict) else []
    if not isinstance(candidates, list):
        return result
    replacements = {}
    for key in ids:
        matches = [row for row in candidates if isinstance(row, dict) and row.get("id") == key]
        if len(matches) == 1:
            resolved = _resolved_candidate(matches[0], catalog, content)
            if resolved is not None:
                replacements[key] = resolved
    return {**result, "goal_checks": [
        replacements.get(row.get("id"), row) if isinstance(row, dict) else row for row in rows
    ]}
