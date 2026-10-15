"""Coverage labels alone cannot excuse missed state transitions."""

from copy import deepcopy

import pytest

from application.editorial_ledger import validate_editorial_observations
from application.errors import StructuredOutputInvalidError

BODY = "她把两只手套戴上。\n\n她褪下右手手套。\n\n她把手套一只一只戴回去。"


def action_report():
    return {"coverage": ["p1", "p2", "p3"], "ledger": [], "findings": [{
        "category": "action_state", "priority": "must_fix", "reason": "Left glove remained worn.",
        "evidence": [
            {"evidence_start": "p2", "evidence_end": "p2", "quote": "她褪下右手手套。"},
            {"evidence_start": "p3", "evidence_end": "p3", "quote": "她把手套一只一只戴回去。"}],
        "suggestion": "Only put the right glove back on."}],
        "action_checks": [
            {"id": "a1", "object": "her gloves", "state": "both worn", "previous_id": None,
                "status": "consistent", "reason": "Initial wearing."},
            {"id": "a2", "object": "her gloves", "state": "left worn, right bare", "previous_id": "a1",
                "status": "consistent", "reason": "Only the right glove is removed."},
            {"id": "a3", "object": "her gloves", "state": "both worn again", "previous_id": "a2",
                "status": "contradiction", "reason": "There was no removal of the left glove."},
        ]}


def test_server_action_candidates_include_each_wearing_transition():
    from application.editorial_actions import action_catalog

    assert action_catalog(BODY) == [
        {"id": "a1", "p": "p1", "quote": "她把两只手套戴上。"},
        {"id": "a2", "p": "p2", "quote": "她褪下右手手套。"},
        {"id": "a3", "p": "p3", "quote": "她把手套一只一只戴回去。"},
    ]


def test_full_paragraph_labels_without_action_checks_are_not_complete():
    from application.editorial_actions import validate_action_coverage

    raw = {"coverage": ["p1", "p2", "p3"], "ledger": [], "findings": []}
    with pytest.raises(StructuredOutputInvalidError, match="action"):
        validate_action_coverage(raw, BODY)


def test_paired_state_finding_and_exhaustive_action_checks_are_valid():
    from application.editorial_actions import validate_action_coverage

    raw = action_report()
    validated = validate_editorial_observations(raw, BODY)
    validate_action_coverage(validated, BODY)
    assert validated["findings"][0]["priority"] == "must_fix"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "future", "different_object", "unreported", "unknown"])
def test_incomplete_or_inconsistent_action_checks_cannot_become_a_pass(mutation):
    from application.editorial_actions import validate_action_coverage

    raw = deepcopy(action_report())
    actions = {
        "missing": lambda: raw["action_checks"].pop(),
        "duplicate": lambda: raw["action_checks"].append(raw["action_checks"][-1]),
        "future": lambda: raw["action_checks"][0].update(previous_id="a3"),
        "different_object": lambda: raw["action_checks"][1].update(object="another person's gloves"),
        "unreported": lambda: raw.update(findings=[]),
        "unknown": lambda: raw["action_checks"][-1].update(status="unknown"),
    }
    actions[mutation]()
    with pytest.raises(StructuredOutputInvalidError):
        validate_action_coverage(raw, BODY)


def test_explicit_restoration_is_not_forced_to_be_a_contradiction():
    from application.editorial_actions import validate_action_coverage

    body = "她把两只手套摘下。\n\n她把两只手套戴回去。"
    raw = {"action_checks": [
        {"id": "a1", "object": "her gloves", "state": "both bare", "previous_id": None,
            "status": "consistent", "reason": "Both removed."},
        {"id": "a2", "object": "her gloves", "state": "both worn", "previous_id": "a1",
            "status": "consistent", "reason": "Both restored."}], "findings": []}
    validate_action_coverage(raw, body)


def test_predecessor_error_identifies_rejected_link_and_server_expected_id():
    from application.editorial_actions import validate_action_coverage

    raw = action_report()
    raw["action_checks"][2]["previous_id"] = "p2"
    with pytest.raises(StructuredOutputInvalidError) as error:
        validate_action_coverage(raw, BODY)
    message = str(error.value)
    assert "a3" in message and "p2" in message and "a2" in message
    assert "her gloves" in message


def test_state_defining_quote_may_precede_a_neutral_same_object_action():
    from application.editorial_actions import validate_action_coverage

    body = BODY.replace("\n\n她把手套一只一只戴回去。",
        "\n\n她检查手套上的灰尘。\n\n她把手套一只一只戴回去。")
    raw = action_report()
    raw["coverage"].append("p4")
    raw["findings"][0]["evidence"][-1].update(evidence_start="p4", evidence_end="p4")
    contradiction = raw["action_checks"].pop()
    raw["action_checks"].append({"id": "a3", "object": "her gloves",
        "state": "left worn, right bare", "previous_id": "a2", "status": "consistent",
        "reason": "Inspecting dust does not remove the left glove."})
    contradiction.update(id="a4", previous_id="a3")
    raw["action_checks"].append(contradiction)
    validated = validate_editorial_observations(raw, body)
    validate_action_coverage(validated, body)


def test_pair_may_use_an_object_not_selected_as_the_paragraph_primary_check():
    from application.editorial_actions import validate_action_coverage

    body = "她只戴上右手手套，收好工作单。\n\n她把两只手套摘下。"
    raw = {"coverage": ["p1", "p2"], "ledger": [], "action_checks": [
        {"id": "a1", "object": "work sheet", "state": "stored", "previous_id": None,
            "status": "consistent", "reason": "The paragraph also establishes right glove only."},
        {"id": "a2", "object": "gloves", "state": "both removed", "previous_id": None,
            "status": "contradiction", "reason": "Left glove was never worn."}],
        "findings": [{"category": "action_state", "priority": "must_fix",
            "reason": "Only the right glove was put on.",
            "evidence": [
                {"evidence_start": "p1", "evidence_end": "p1", "quote": body.split("\n")[0]},
                {"evidence_start": "p2", "evidence_end": "p2", "quote": "她把两只手套摘下。"}],
            "suggestion": "Only remove the right glove."}]}
    validate_action_coverage(validate_editorial_observations(raw, body), body)


def test_descriptive_state_without_an_action_cue_can_ground_a_pair():
    from application.editorial_actions import validate_action_coverage

    body = "两只手套都在桌面上。\n\n她戴回右手手套。\n\n她把两只手套摘下。"
    raw = {"coverage": ["p1", "p2", "p3"], "ledger": [], "action_checks": [
        {"id": "a1", "object": "gloves", "state": "right worn, left on desk", "previous_id": None,
            "status": "consistent", "reason": "Only right glove restored."},
        {"id": "a2", "object": "gloves", "state": "both removed", "previous_id": "a1",
            "status": "contradiction", "reason": "Left glove was never worn."}],
        "findings": [{"category": "action_state", "priority": "must_fix",
            "reason": "Initial state is explicitly on the desk; only right restored.",
            "evidence": [
                {"evidence_start": "p1", "evidence_end": "p1", "quote": "两只手套都在桌面上。"},
                {"evidence_start": "p3", "evidence_end": "p3", "quote": "她把两只手套摘下。"}],
            "suggestion": "Only remove the right glove."}]}
    validate_action_coverage(validate_editorial_observations(raw, body), body)


def test_paired_finding_cannot_use_current_paragraph_as_its_earlier_evidence():
    from application.editorial_actions import validate_action_coverage

    raw = action_report()
    raw["findings"][0]["evidence"][0] = raw["findings"][0]["evidence"][-1]
    with pytest.raises(StructuredOutputInvalidError, match="paired finding"):
        validate_action_coverage(raw, BODY)
