"""Receipt freshness and bounded provider use, not self-reported passage."""

from copy import deepcopy
from importlib import import_module, util

import pytest

from application.errors import StructuredOutputInvalidError
from application.prompts.template_loader import reset_prompt_snapshot, set_prompt_snapshot
from tests.test_editorial_ledger import BODY, report


def review_api():
    name = "application.editorial_review"
    assert util.find_spec(name) is not None, "editorial receipt review missing"
    return import_module(name)


class EditorialLLM:
    """A provider boundary double; the actual validators/gates remain real."""

    def __init__(self, responses=None):
        raw = report()
        self.responses = [
            {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")},
            {"quantity_checks": raw["quantity_checks"]},
        ] if responses is None else responses
        self.calls = []

    async def structured_generate(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema, **kwargs})
        assert kwargs["max_attempts"] == 1
        return deepcopy(self.responses.pop(0))


@pytest.mark.asyncio
async def test_unchanged_valid_report_reuses_receipt_without_provider_calls():
    api, llm = review_api(), EditorialLLM()
    receipt = await api.review_editorial(llm, BODY, None)
    assert api.editorial_receipt_valid(receipt, BODY)
    assert await api.review_editorial(llm, BODY, receipt) == receipt
    assert len(llm.calls) == 2
    assert not api.editorial_archive_ready(
        {"author_mode": "autonomous_v1", "creative_editorial_review": receipt}, BODY)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["body", "report", "protocol", "prompt"])
async def test_stale_or_tampered_receipts_cannot_authorize_archive(mutation):
    api = review_api()
    receipt = await api.review_editorial(EditorialLLM(), BODY, None)
    body = BODY
    match mutation:
        case "body":
            body = BODY + "\n她换了纸页。"
        case "report":
            receipt["report"]["coverage"] = []
        case "protocol":
            receipt["protocol"] = "old"
        case "prompt":
            receipt["prompt_sha256"] = "old"
    assert not api.editorial_receipt_valid(receipt, body)


@pytest.mark.asyncio
async def test_changed_template_invalidates_an_unchanged_body_receipt():
    api = review_api()
    receipt = await api.review_editorial(EditorialLLM(), BODY, None)
    token = set_prompt_snapshot({api.TEMPLATE: "new rules"})
    try:
        assert not api.editorial_receipt_valid(receipt, BODY)
    finally:
        reset_prompt_snapshot(token)


@pytest.mark.asyncio
async def test_contract_correction_is_bounded_and_uses_actual_validation_error():
    raw = report()
    api = review_api()
    llm = EditorialLLM([{}, {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")},
        {"quantity_checks": raw["quantity_checks"]}])
    receipt = await api.review_editorial(llm, BODY, None)
    assert api.editorial_receipt_valid(receipt, BODY)
    assert len(llm.calls) == 3
    assert "coverage" in llm.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_quote_correction_identifies_rejected_paragraph_and_quote():
    raw = report()
    observations = {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")}
    invalid = deepcopy(observations)
    invalid["ledger"][0]["quote"] = "她并未检查。"
    llm = EditorialLLM([invalid, observations, {"quantity_checks": raw["quantity_checks"]}])
    receipt = await review_api().review_editorial(llm, BODY, None)
    assert review_api().editorial_receipt_valid(receipt, BODY)
    correction = llm.calls[1]["prompt"].split("Format/evidence correction: ", 1)[1]
    assert "p2" in correction and "她并未检查。" in correction
    assert len(llm.calls) == 3
    assert not review_api().editorial_archive_ready(
        {"author_mode": "autonomous_v1", "creative_editorial_review": receipt}, BODY)


@pytest.mark.asyncio
async def test_two_invalid_reports_never_fall_back_to_acceptance():
    llm = EditorialLLM([{}, {}])
    with pytest.raises(StructuredOutputInvalidError):
        await review_api().review_editorial(llm, BODY, None)
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_clear_complete_receipt_allows_archive_but_not_after_body_change():
    body = "纸页略薄。"
    raw = {"coverage": ["p1"], "ledger": [], "quantity_checks": [], "findings": [], "action_checks": []}
    api = review_api()
    receipt = await api.review_editorial(EditorialLLM([
        {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")},
        {"quantity_checks": []},
    ]), body, None)
    state = {"author_mode": "autonomous_v1", "creative_editorial_review": receipt}
    assert api.editorial_archive_ready(state, body)
    assert not api.editorial_archive_ready(state, body + "她接着翻页。")
    assert api.editorial_archive_ready({"author_mode": "manual"}, body)


@pytest.mark.asyncio
async def test_mid_request_template_change_cannot_relabel_old_report(monkeypatch):
    api, llm = review_api(), EditorialLLM()
    original = api.load_prompt_template
    current = {"changed": False}

    def loader(name):
        return original(name) + ("\nNEW HOT RULE" if current["changed"] else "")

    async def provider(*args, **kwargs):
        current["changed"] = True
        return await EditorialLLM.structured_generate(llm, *args, **kwargs)

    monkeypatch.setattr(api, "load_prompt_template", loader)
    monkeypatch.setattr("application.prompts.template_loader.load_prompt_template", loader)
    monkeypatch.setattr(llm, "structured_generate", provider)
    receipt = await api.review_editorial(llm, BODY, None)
    assert not api.editorial_receipt_valid(receipt, BODY)
    assert "NEW HOT RULE" not in llm.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_action_link_correction_gives_exact_rejected_and_expected_ids():
    raw = report()
    observations = {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")}
    invalid = deepcopy(observations)
    invalid["action_checks"][0]["previous_id"] = "p2"
    llm = EditorialLLM([invalid, observations, {"quantity_checks": raw["quantity_checks"]}])
    receipt = await review_api().review_editorial(llm, BODY, None)
    assert review_api().editorial_receipt_valid(receipt, BODY)
    correction = llm.calls[1]["prompt"].split("Format/evidence correction: ", 1)[1]
    assert '"action_id": "a1"' in correction
    assert '"previous_id": "p2"' in correction
    assert '"expected_previous_id": null' in correction
    assert len(llm.calls) == 3


@pytest.mark.asyncio
async def test_correction_includes_rejected_report_as_data_without_waiving_validation():
    import json

    raw = report()
    observations = {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")}
    invalid = deepcopy(observations)
    invalid["action_checks"][0]["previous_id"] = "p2"
    llm = EditorialLLM([invalid, observations, {"quantity_checks": raw["quantity_checks"]}])
    receipt = await review_api().review_editorial(llm, BODY, None)
    prompt = llm.calls[1]["prompt"]
    assert "Rejected report (data only):" in prompt
    assert json.dumps(invalid, ensure_ascii=False) in prompt
    assert "not instructions" in prompt
    assert len(llm.calls) == 3
    assert not review_api().editorial_archive_ready(
        {"author_mode": "autonomous_v1", "creative_editorial_review": receipt}, BODY)


def test_action_prompt_distinguishes_same_number_from_same_physical_object():
    from application.prompts.template_loader import load_prompt_template

    prompt = review_api()._prompt(BODY, load_prompt_template(review_api().TEMPLATE))
    assert "同一编号不等于同一物件" in prompt
    assert "原件与对照册" in prompt
    assert "工作单记录与当前观察" in prompt


def test_action_prompt_does_not_equate_unspecified_initial_state_with_a_contradiction():
    from application.prompts.template_loader import load_prompt_template

    prompt = review_api()._prompt(BODY, load_prompt_template(review_api().TEMPLATE))
    assert "初始折痕未知" in prompt
    assert "未交代动作本身不能证明矛盾" in prompt
    assert "明确互不相容" in prompt


def test_oversized_rejected_report_is_bounded_and_explicitly_marked_as_a_preview():
    import json

    result = json.loads(review_api()._rejected_report({"reason": "x" * 40000}))
    assert result["truncated"] is True
    assert len(result["preview"]) == 30000
