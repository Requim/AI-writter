"""Restored measured nodes must not hide newly versioned editorial rules."""

from copy import deepcopy
import hashlib
import json

import pytest

from application.agents.reflection_node import _generate_valid_review
from application.editorial_review import advance_editorial
from application.prompts.reflection_prompts import AGGREGATION_SCHEMA
from application.runtime_observability import measured_node
from tests.test_editorial_ledger import BODY, report
from tests.test_prompt_quality_pipeline import _review_result


LEGACY_SNAPSHOT = {
    "reflection/editorial_ledger_v1.txt": "FROZEN_LEGACY_OBSERVATIONS\n$catalog",
    "reflection/editorial_quantities_v1.txt": "FROZEN_LEGACY_QUANTITIES\n$measurements",
    "reflection/copyediting_v1.txt": "FROZEN_LEGACY_COPYEDITING",
}


class ReviewProvider:
    def __init__(self):
        self.calls = []

    async def structured_generate(self, prompt, schema, **kwargs):
        self.calls.append({"prompt": prompt, "schema": schema})
        raw = report()
        if "coverage" in schema:
            return {key: raw[key] for key in ("coverage", "ledger", "findings", "action_checks")}
        if "quantity_checks" in schema:
            return {"quantity_checks": raw["quantity_checks"]}
        return _review_result(4.5)


def legacy_partial_receipt():
    raw = report()
    observations = {key: raw[key] for key in ("coverage", "ledger", "findings")}
    prompt = LEGACY_SNAPSHOT["reflection/editorial_ledger_v1.txt"] + "\n" + (
        LEGACY_SNAPSHOT["reflection/editorial_quantities_v1.txt"])
    return {
        "protocol": "editorial-ledger-split-v2",
        "body_sha256": hashlib.sha256(BODY.encode()).hexdigest(),
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "observations": observations,
        "observation_sha256": hashlib.sha256(json.dumps(
            observations, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest(),
    }


@pytest.mark.asyncio
async def test_restored_editorial_rechecks_old_partial_with_new_versioned_rules():
    state = {"prompt_snapshot": deepcopy(LEGACY_SNAPSHOT)}
    before = deepcopy(state)
    provider = ReviewProvider()
    cached = legacy_partial_receipt()

    async def review(state):
        return await advance_editorial(provider, BODY, cached)

    receipt = await measured_node("reflection_node", review)(state)
    assert "observations" in receipt and "report" not in receipt
    assert receipt["prompt_sha256"] != cached["prompt_sha256"]
    assert len(provider.calls) == 1 and "coverage" in provider.calls[0]["schema"]
    assert "容纳" in provider.calls[0]["prompt"]
    assert state == before


@pytest.mark.asyncio
async def test_restored_literary_review_gets_new_rules_without_rewriting_snapshot():
    state = {"prompt_snapshot": deepcopy(LEGACY_SNAPSHOT)}
    before = deepcopy(state)
    provider = ReviewProvider()

    async def review(state):
        return await _generate_valid_review(provider, "Current prose", AGGREGATION_SCHEMA)

    await measured_node("reflection_node", review)(state)
    assert len(provider.calls) == 1
    assert "物件关系" in provider.calls[0]["prompt"]
    assert state == before
