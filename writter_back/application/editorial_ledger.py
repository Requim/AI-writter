"""Validate compact editorial observations against immutable prose positions."""

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from application.errors import StructuredOutputInvalidError
from application.editorial_actions import ActionCheck
from application.source_spans import source_catalog, source_span

MEASUREMENT = re.compile(
    r"(?:[0-9]+(?:\.[0-9]+)?(?:/[0-9]+(?:\.[0-9]+)?)?|"
    r"[零〇一二两三四五六七八九十百千万半]+"
    r"(?:(?:点|分之)[零〇一二两三四五六七八九十百千万半]+)?)\s*"
    r"(?:毫米|厘米|千米|公里|米|寸|尺|秒|分钟|小时|摄氏度|度)"
)
FIGURATIVE_CUE = re.compile(
    r"夸张|比喻|打比方|开玩笑|说笑|吹牛|撒谎|谎话|仿佛|好像|"
    r"\b(?:hyperbole|exaggerat\w*|metaphor|jok\w*|lying|lie)\b", re.I,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _SourceQuote(_StrictModel):
    evidence_start: str = Field(min_length=1)
    evidence_end: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _Observation(_StrictModel):
    p: str = Field(min_length=1)
    kind: Literal["action", "quantity", "date", "claim"]
    fact: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class _QuantityCheck(_StrictModel):
    id: str = Field(min_length=1)
    reading: Literal["literal", "figurative"]
    status: Literal["plausible", "implausible", "unknown"]
    reason: str = Field(min_length=1)
    qualifier: _SourceQuote | None


class _Finding(_StrictModel):
    category: Literal["unit", "action_state", "calendar", "count", "other"]
    priority: Literal["must_fix", "optional"]
    reason: str = Field(min_length=1)
    evidence: list[_SourceQuote] = Field(min_length=1)
    suggestion: str = Field(min_length=1)


class _ObservationReport(_StrictModel):
    coverage: list[str]
    ledger: list[_Observation]
    findings: list[_Finding]
    action_checks: list[ActionCheck] | None = None


class _QuantityReport(_StrictModel):
    quantity_checks: list[_QuantityCheck]


class EditorialReport(_ObservationReport):
    quantity_checks: list[_QuantityCheck]


def measurement_catalog(content: str) -> list[dict]:
    result: list[dict] = []
    for paragraph in source_catalog(content):
        for match in MEASUREMENT.finditer(paragraph["text"]):
            result.append({
                "id": f"m{len(result) + 1}", "p": paragraph["id"],
                "quote": match.group(), "start": paragraph["start"] + match.start(),
                "end": paragraph["start"] + match.end(),
            })
    return result


def _resolve_quote(quote: dict, content: str) -> dict:
    try:
        resolved = source_span(quote, content)
        if resolved is None:
            raise ValueError("missing source paragraph")
    except ValueError as exc:
        reference = f"{quote.get('evidence_start')}..{quote.get('evidence_end')}"
        rejected = str(quote.get("quote") or "")[:160]
        raise ValueError(f"{reference}, rejected_quote={rejected!r}: {exc}") from exc
    return {**quote, "start": resolved[0]}


def _validate_observations(report: dict, content: str, catalog: list[dict]) -> None:
    if not catalog or report["coverage"] != [row["id"] for row in catalog]:
        raise ValueError("paragraph coverage is incomplete or unordered")
    for observation in report["ledger"]:
        _resolve_quote({"evidence_start": observation["p"],
            "evidence_end": observation["p"], "quote": observation["quote"]}, content)


def _validate_qualifier(check: dict, measurement: dict, content: str) -> None:
    qualifier = check["qualifier"]
    if check["reading"] == "literal":
        if qualifier is not None:
            raise ValueError("literal measurement cannot carry a figurative qualifier")
        return
    if qualifier is None:
        raise ValueError("figurative measurement requires supported nonliteral reading")
    _resolve_quote(qualifier, content)
    position = int(measurement["p"][1:])
    first, last = int(qualifier["evidence_start"][1:]), int(qualifier["evidence_end"][1:])
    if first < position - 1 or last > position + 1:
        raise ValueError("figurative cue is unrelated to the measurement paragraph")
    if not FIGURATIVE_CUE.search(qualifier["quote"]):
        raise ValueError("figurative reading has no explicit source cue")


def _validate_quantities(report: dict, content: str) -> None:
    measurements = measurement_catalog(content)
    checks = report["quantity_checks"]
    if [row["id"] for row in checks] != [row["id"] for row in measurements]:
        raise ValueError("measurement coverage is incomplete or unordered")
    for check, measurement in zip(checks, measurements):
        if check["status"] == "unknown":
            raise ValueError("quantity judgment remains unknown")
        _validate_qualifier(check, measurement, content)


def _validate_findings(report: dict, content: str) -> None:
    for finding in report["findings"]:
        evidence = [_resolve_quote(quote, content) for quote in finding["evidence"]]
        positions = [row["start"] for row in evidence]
        if len(set(positions)) != len(positions) or positions != sorted(positions):
            raise ValueError("contradiction evidence is duplicate or unordered")
        if finding["category"] in {"action_state", "calendar"} and len(evidence) < 2:
            raise ValueError("action/date contradiction requires paired original quotes")


def validate_editorial_report(raw: object, content: str) -> dict:
    try:
        report = EditorialReport.model_validate(raw).model_dump()
        _validate_observations(report, content, source_catalog(content))
        _validate_quantities(report, content)
        _validate_findings(report, content)
        return report
    except (ValueError, ValidationError) as exc:
        raise StructuredOutputInvalidError(
            f"Editorial evidence validation failed: {str(exc)[:600]}"
        ) from exc


def validate_editorial_observations(raw: object, content: str) -> dict:
    try:
        report = _ObservationReport.model_validate(raw).model_dump()
        _validate_observations(report, content, source_catalog(content))
        _validate_findings(report, content)
        return report
    except ValueError as exc:
        raise StructuredOutputInvalidError(f"Editorial observation validation failed: {str(exc)[:600]}") from exc


def validate_editorial_quantities(raw: object, content: str) -> dict:
    try:
        report = _QuantityReport.model_validate(raw).model_dump()
        _validate_quantities(report, content)
        return report
    except ValueError as exc:
        raise StructuredOutputInvalidError(f"Editorial quantity validation failed: {str(exc)[:600]}") from exc


def _issue(category: str, reason: str, priority: str, evidence: list[dict],
           suggestion: str, content: str) -> dict:
    anchor = evidence[-1]
    identity = f"{hashlib.sha256(content.encode()).hexdigest()}:{category}:{anchor['start']}"
    return {
        "issue_id": f"editorial-{hashlib.sha256(identity.encode()).hexdigest()[:16]}",
        "type": f"editorial_{category}", "severity": "high" if priority == "must_fix" else "low",
        "priority_action": priority, "issue_resolved": False, "evidence_valid": True,
        "location": anchor["evidence_start"], "description": reason,
        "evidence": anchor["quote"], "source_evidence": evidence, "suggestion": suggestion,
    }


def editorial_issues(report: dict, content: str) -> list[dict]:
    checked = validate_editorial_report(report, content)
    paragraphs = {row["id"]: row for row in source_catalog(content)}
    issues = []
    for check, measurement in zip(checked["quantity_checks"], measurement_catalog(content)):
        if check["reading"] == "literal" and check["status"] == "implausible":
            p = measurement["p"]
            evidence = [_resolve_quote({"evidence_start": p, "evidence_end": p,
                "quote": paragraphs[p]["text"]}, content)]
            issues.append(_issue("unit", check["reason"], "must_fix", evidence,
                "Correct the cited object's unit or magnitude without changing the scene.", content))
    for finding in checked["findings"]:
        evidence = [_resolve_quote(row, content) for row in finding["evidence"]]
        reason = finding["reason"] + "\n" + "\n".join(row["quote"] for row in evidence)
        issues.append(_issue(finding["category"], reason, finding["priority"], evidence,
            finding["suggestion"], content))
    return issues
