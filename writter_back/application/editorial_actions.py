"""Enumerate literal action cues; semantics remain an evidence-based review."""

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from application.errors import StructuredOutputInvalidError
from application.source_spans import source_catalog

ACTION_CUE = re.compile("戴|摘|褪|脱|穿|握|捏|拿|取|抽|放|收|交|递|翻|打开|关门|关上|合上|检查|核对|比对|封存|刮|擦")


class ActionCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    object: str = Field(min_length=1)
    state: str = Field(min_length=1)
    previous_id: str | None
    status: Literal["consistent", "contradiction", "not_applicable", "unknown"]
    reason: str = Field(min_length=1)


def action_catalog(content: str) -> list[dict]:
    """Cues request inspection, not automatic judgments of prose or physics."""
    paragraphs = [row for row in source_catalog(content) if ACTION_CUE.search(row["text"])]
    return [{"id": f"a{index}", "p": row["id"], "quote": row["text"]}
        for index, row in enumerate(paragraphs, 1)]


def _contradiction_reported(check, catalog, findings, positions):
    after = catalog[check["id"]]["p"]
    current = positions[after]
    return any(finding.get("category") == "action_state" and finding.get("priority") == "must_fix"
        and len(finding.get("evidence") or []) >= 2
        and any(positions.get(row.get("evidence_start"), current) <=
            positions.get(row.get("evidence_end"), current) < current
            for row in finding["evidence"][:-1])
        and finding["evidence"][-1].get("evidence_start") == after
        for finding in findings)


def _contradiction_error(row, catalog, findings):
    pairs = [{"category": item.get("category"), "priority": item.get("priority"),
        "paragraphs": [quote.get("evidence_start") for quote in item.get("evidence") or []]}
        for item in findings[:3]]
    detail = {"action_id": row["id"], "object": row["object"][:40],
        "current_paragraph": catalog[row["id"]]["p"],
        "required": "A real earlier source paragraph, not necessarily a same-object action check.",
        "reported_findings": pairs}
    return "action contradiction requires a grounded paired finding; " + json.dumps(detail, ensure_ascii=False)


def _link_error(row, previous, expected):
    fields = {
        "action_id": row["id"], "object": row["object"], "previous_id": row["previous_id"],
        "expected_previous_id": expected,
        "linked_object": previous["object"] if previous else None,
    }
    fields = {key: value[:80] if isinstance(value, str) else value for key, value in fields.items()}
    return ("action predecessor is missing, future or another object; "
        + json.dumps(fields, ensure_ascii=False)
        + ". Use action IDs (aN), not paragraph IDs (pN); keep identical object names.")


def _validate_checks(checks, candidates, findings, positions):
    if [row["id"] for row in checks] != [row["id"] for row in candidates]:
        raise ValueError("action coverage is incomplete or unordered")
    catalog = {row["id"]: row for row in candidates}
    prior, objects = {}, {}
    for row in checks:
        previous = prior.get(row["previous_id"])
        if row["status"] == "unknown":
            raise ValueError("action state remains unknown")
        if row["previous_id"] is not None and (previous is None or previous["object"] != row["object"]):
            raise ValueError(_link_error(row, previous, objects.get(row["object"])))
        if row["status"] != "not_applicable" and row["previous_id"] != objects.get(row["object"]):
            raise ValueError(_link_error(row, previous, objects.get(row["object"])))
        if row["status"] == "contradiction" and not _contradiction_reported(row, catalog, findings, positions):
            raise ValueError(_contradiction_error(row, catalog, findings))
        prior[row["id"]] = row
        if row["status"] != "not_applicable":
            objects[row["object"]] = row["id"]


def validate_action_coverage(report: dict, content: str) -> None:
    try:
        checks = TypeAdapter(list[ActionCheck]).validate_python(report.get("action_checks"), strict=True)
        positions = {row["id"]: index for index, row in enumerate(source_catalog(content))}
        _validate_checks([row.model_dump() for row in checks], action_catalog(content),
            report.get("findings") or [], positions)
    except ValueError as exc:
        raise StructuredOutputInvalidError(f"Editorial action validation failed: {str(exc)[:600]}") from exc
