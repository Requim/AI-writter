"""Source evidence and counterexamples for autonomous manuscript review."""

from copy import deepcopy
from importlib import import_module, util

import pytest

from application.errors import StructuredOutputInvalidError

BODY = "纸页薄了一寸。\n\n她检查了装订线。\n\n她说装订线没查。"


def ledger_api():
    name = "application.editorial_ledger"
    assert util.find_spec(name) is not None, "source-bound editorial validator missing"
    return import_module(name)


def report():
    return {
        "coverage": ["p1", "p2", "p3"],
        "ledger": [{"p": "p2", "kind": "action", "fact": "binding checked",
                    "quote": "她检查了装订线。"}],
        "action_checks": [{"id": "a1", "object": "binding", "state": "checked",
            "previous_id": None, "status": "consistent", "reason": "inspection recorded"}],
        "quantity_checks": [{"id": "m1", "reading": "literal",
            "status": "implausible", "reason": "single sheet cannot differ by 3cm",
            "qualifier": None}],
        "findings": [{"category": "action_state", "priority": "must_fix",
            "reason": "same inspection both completed and not performed",
            "evidence": [
                {"evidence_start": "p2", "evidence_end": "p2", "quote": "她检查了装订线。"},
                {"evidence_start": "p3", "evidence_end": "p3", "quote": "她说装订线没查。"}],
            "suggestion": "distinguish initial inspection from further checks"}],
    }


def test_unit_and_action_issues_block_even_without_a_score():
    api = ledger_api()
    checked = api.validate_editorial_report(report(), BODY)
    issues = api.editorial_issues(checked, BODY)
    assert len(issues) == 2
    assert {item["priority_action"] for item in issues} == {"must_fix"}
    assert issues[0]["evidence"] == "纸页薄了一寸。"
    assert issues[1]["evidence"] == "她说装订线没查。"
    assert len(issues[1]["source_evidence"]) == 2


def test_server_measurement_positions_preserve_blank_lines():
    rows = ledger_api().measurement_catalog(BODY)
    assert rows == [{"id": "m1", "p": "p1", "quote": "一寸", "start": 4, "end": 6}]


@pytest.mark.parametrize(("body", "quote", "start", "end"), [
    ("桌子高一点五米。", "一点五米", 3, 7),
    ("木板长三分之一米。", "三分之一米", 3, 8),
    ("桌高1.5米。", "1.5米", 2, 6),
    ("木板长1/2米。", "1/2米", 3, 7),
])
def test_decimal_and_fractional_amounts_are_not_truncated(body, quote, start, end):
    rows = ledger_api().measurement_catalog(body)
    assert rows == [{"id": "m1", "p": "p1", "quote": quote, "start": start, "end": end}]


@pytest.mark.parametrize("mutation", [
    "missing_paragraph", "duplicate_paragraph", "unknown_paragraph",
    "missing_quantity", "duplicate_quantity", "fake_ledger_quote",
    "fake_finding_quote", "single_action_quote", "reversed_pair", "unknown_quantity",
])
def test_invalid_or_incomplete_evidence_cannot_become_a_valid_review(mutation):
    raw = report()
    match mutation:
        case "missing_paragraph":
            raw["coverage"].pop()
        case "duplicate_paragraph":
            raw["coverage"][1] = "p1"
        case "unknown_paragraph":
            raw["coverage"][1] = "p9"
        case "missing_quantity":
            raw["quantity_checks"] = []
        case "duplicate_quantity":
            raw["quantity_checks"] *= 2
        case "fake_ledger_quote":
            raw["ledger"][0]["quote"] = "她并未检查。"
        case "fake_finding_quote":
            raw["findings"][0]["evidence"][1]["quote"] = "她已经查完。"
        case "single_action_quote":
            raw["findings"][0]["evidence"].pop()
        case "reversed_pair":
            raw["findings"][0]["evidence"].reverse()
        case _:
            raw["quantity_checks"][0]["status"] = "unknown"
    with pytest.raises(StructuredOutputInvalidError):
        ledger_api().validate_editorial_report(raw, BODY)


def figurative_report(body):
    raw = deepcopy(report())
    raw.update(coverage=["p1"], ledger=[], findings=[])
    raw["quantity_checks"][0].update(reading="figurative", status="plausible",
        qualifier={"evidence_start": "p1", "evidence_end": "p1", "quote": body})
    return raw


def test_explicit_joke_quote_may_include_the_measurement():
    body = "他故意夸张地说纸薄了一寸，大家知道他在开玩笑。"
    api = ledger_api()
    result = api.validate_editorial_report(figurative_report(body), body)
    assert api.editorial_issues(result, body) == []


def test_physically_implausible_explicit_hyperbole_is_not_a_narrative_defect():
    body = "他故意夸张地说纸薄了一寸，大家知道他在开玩笑。"
    raw = figurative_report(body)
    raw["quantity_checks"][0]["status"] = "implausible"
    api = ledger_api()
    assert api.editorial_issues(api.validate_editorial_report(raw, body), body) == []


@pytest.mark.parametrize("quote", ["一寸", "纸页薄了一寸。"])
def test_invented_figurative_reading_needs_an_actual_cue(quote):
    body = "纸页薄了一寸。"
    raw = figurative_report(body)
    raw["quantity_checks"][0]["qualifier"]["quote"] = quote
    with pytest.raises(StructuredOutputInvalidError):
        ledger_api().validate_editorial_report(raw, body)


def test_unrelated_distant_joke_cannot_excuse_a_literal_measurement():
    body = BODY + "\n\n他在开玩笑。"
    raw = report()
    raw["coverage"].append("p4")
    raw["quantity_checks"][0].update(reading="figurative", status="plausible",
        qualifier={"evidence_start": "p4", "evidence_end": "p4", "quote": "他在开玩笑。"})
    with pytest.raises(StructuredOutputInvalidError):
        ledger_api().validate_editorial_report(raw, body)


def test_real_stack_measurement_and_restoration_are_not_forced_errors():
    body = "纸垫厚两寸，抽走一半就薄了一寸。\n\n她摘下手套，随后重新戴上再摸木板。"
    raw = report()
    raw.update(coverage=["p1", "p2"], ledger=[], findings=[])
    raw["quantity_checks"] = [
        {"id": "m1", "reading": "literal", "status": "plausible",
         "reason": "stack thickness", "qualifier": None},
        {"id": "m2", "reading": "literal", "status": "plausible",
         "reason": "half the stack removed", "qualifier": None},
    ]
    api = ledger_api()
    assert api.editorial_issues(api.validate_editorial_report(raw, body), body) == []
