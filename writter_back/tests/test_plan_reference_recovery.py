"""Resume volume four with exact earlier IDs and chapter-specific arc bounds."""

from copy import deepcopy
import json

import pytest

from application.agents.novel_plan_node import novel_plan_initialize_node, novel_plan_volume_node
from application.errors import RetryableWorkflowError
from application.prompts.novel_plan_prompts import VOLUME_SLOTS_SCHEMA
from application.prompts.template_loader import (
    load_prompt_template, reset_prompt_snapshot, set_prompt_snapshot,
)
from tests.test_novel_planning_workflow import PlanningLLM
from tests.test_plan_generation_context import _context, _fixture


def _references(prompt):
    marker = "\n[Planning Reference Catalog]\n"
    if marker not in prompt:
        return None
    return json.JSONDecoder().raw_decode(prompt.split(marker, 1)[1])[0]


class ReferencePlanner(PlanningLLM):
    def __init__(self, fault=None):
        super().__init__(80, 336_000)
        self.fault = fault
        self.prompts = []

    async def structured_generate(self, prompt, schema, **kwargs):
        if schema is not VOLUME_SLOTS_SCHEMA:
            return await super().structured_generate(prompt, schema, **kwargs)
        self.prompts.append(prompt)
        if self.fault == "provider":
            raise RuntimeError("provider unavailable")
        references = _references(prompt)
        slots = [self._slot(number, 4) for number in range(61, 81)]
        for slot in slots:
            slot["arc_ids"] = (
                references["arc_ids_by_chapter"][str(slot["chapter_number"])]
                if references else ["arc-main", "arc-side"]
            )
        slots[5]["payoff_ids"] = ["internal-memo" if references else "payoff-internal-memo"]
        slots[7]["setup_ids"] = ["setup-seal"]
        slots[8]["payoff_ids"] = ["setup-seal"]
        slots[-1]["payoff_ids"] = ["water-debt" if references else "payoff-water-debt"]
        if self.fault == "alias":
            slots[5]["payoff_ids"] = ["payoff-internal-memo"]
        if self.fault == "arc":
            slots[-1]["arc_ids"] = ["arc-side"]
        return {"chapter_slots": slots}


class MacroLabelPlanner(ReferencePlanner):
    async def structured_generate(self, prompt, schema, **kwargs):
        result = await super().structured_generate(prompt, schema, **kwargs)
        volume = _context(prompt)["blueprint"]["volumes"][-1]
        if "payoff-internal-memo" in volume.get("payoff_ids", []):
            result["chapter_slots"][5]["payoff_ids"] = ["payoff-internal-memo"]
        return result


async def _resume_fixture(fault=None):
    repo, llm, cfg, state = await _fixture()
    state.update((await novel_plan_initialize_node(state, cfg)).update)
    generation = state["plan_generation"]
    for index, volume in enumerate(generation["blueprint"]["volumes"]):
        volume.update(start_chapter=index * 20 + 1, end_chapter=(index + 1) * 20)
    generation["blueprint"]["arcs"].append({
        **generation["blueprint"]["arcs"][0], "arc_id": "arc-side", "end_chapter": 76,
    })
    generation["blueprint"]["volumes"][-1].update(
        setup_ids=["setup-seal"], payoff_ids=["payoff-water-debt", "payoff-internal-memo"],
    )
    generation["chapter_slots"] = [
        llm._slot(number, (number - 1) // 20 + 1) for number in range(1, 61)
    ]
    generation["chapter_slots"][0]["setup_ids"] = ["water-debt", "paid-clue"]
    generation["chapter_slots"][11]["payoff_ids"] = ["paid-clue"]
    generation["chapter_slots"][50]["setup_ids"] = ["internal-memo"]
    generation["next_volume_index"] = 3
    repo.session["counters"] = {"preparation": 23}
    planner = ReferencePlanner(fault)
    cfg["configurable"]["llm_config"]["llm_instance"] = planner
    return repo, planner, cfg, state


@pytest.mark.asyncio
async def test_volume_four_resumes_with_valid_literal_ids_without_changing_earlier_slots():
    repo, planner, cfg, state = await _resume_fixture()
    before, counters = deepcopy(state), deepcopy(repo.session["counters"])
    command = await novel_plan_volume_node(state, cfg)
    generated = command.update["plan_generation"]
    assert command.goto == "novel_plan_finalize_node"
    assert len(generated["chapter_slots"]) == 80
    assert generated["chapter_slots"][:60] == before["plan_generation"]["chapter_slots"]
    assert generated["chapter_slots"][65]["payoff_ids"] == ["internal-memo"]
    assert generated["chapter_slots"][79]["arc_ids"] == ["arc-main"]
    assert state == before
    assert repo.session["counters"] == counters
    assert len(planner.prompts) == 1


@pytest.mark.asyncio
async def test_catalog_contains_paid_and_early_ids_but_excludes_retained_future_slots():
    _repo, planner, cfg, state = await _resume_fixture()
    state["plan_generation"]["chapter_slots"].append({
        **PlanningLLM._slot(80, 4), "setup_ids": ["future-clue"],
    })
    await novel_plan_volume_node(state, cfg)
    catalog = _references(planner.prompts[0])
    assert catalog["prior_foreshadowing"] == {
        "water-debt": {"setup_chapters": [1], "payoff_chapters": []},
        "paid-clue": {"setup_chapters": [1], "payoff_chapters": [12]},
        "internal-memo": {"setup_chapters": [51], "payoff_chapters": []},
    }
    assert catalog["arc_ids_by_chapter"]["76"] == ["arc-main", "arc-side"]
    assert catalog["arc_ids_by_chapter"]["77"] == ["arc-main"]
    assert set(catalog["arc_ids_by_chapter"]) == {str(number) for number in range(61, 81)}


@pytest.mark.asyncio
async def test_frozen_old_templates_still_receive_new_reference_catalog():
    _repo, planner, cfg, state = await _resume_fixture()
    snapshot = {
        name: load_prompt_template(name) for name in (
            "outline/plan_volume_slots.txt", "creative/plan_generation_consistency_v1.txt",
        )
    }
    before = deepcopy(snapshot)
    token = set_prompt_snapshot(snapshot)
    try:
        command = await novel_plan_volume_node(state, cfg)
    finally:
        reset_prompt_snapshot(token)
    assert command.goto == "novel_plan_finalize_node"
    assert _references(planner.prompts[0])["prior_foreshadowing"]["water-debt"] == {
        "setup_chapters": [1], "payoff_chapters": [],
    }
    assert snapshot == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["alias", "arc"])
async def test_invalid_provider_ids_and_arc_bounds_are_still_rejected(fault):
    repo, planner, cfg, state = await _resume_fixture(fault)
    before = deepcopy(state)
    with pytest.raises(RetryableWorkflowError):
        await novel_plan_volume_node(state, cfg)
    assert len(planner.prompts) == 3
    assert state == before
    assert repo.session["counters"] == {"preparation": 23}


@pytest.mark.asyncio
async def test_reference_recovery_does_not_hide_provider_failures():
    _repo, planner, cfg, state = await _resume_fixture("provider")
    before = deepcopy(state)
    with pytest.raises(RuntimeError, match="provider unavailable"):
        await novel_plan_volume_node(state, cfg)
    assert state == before
    assert len(planner.prompts) == 1


@pytest.mark.asyncio
async def test_competing_macro_labels_are_not_model_reference_candidates():
    _repo, _planner, cfg, state = await _resume_fixture()
    planner = MacroLabelPlanner()
    cfg["configurable"]["llm_config"]["llm_instance"] = planner
    before = deepcopy(state)
    command = await novel_plan_volume_node(state, cfg)
    assert command.goto == "novel_plan_finalize_node"
    projected = _context(planner.prompts[0])["blueprint"]
    expected = deepcopy(before["plan_generation"]["blueprint"])
    for volume in expected["volumes"]:
        volume.pop("setup_ids")
        volume.pop("payoff_ids")
    assert projected == expected
    assert state == before
    assert command.update["plan_generation"]["blueprint"] == before["plan_generation"]["blueprint"]


@pytest.mark.asyncio
async def test_primary_volume_prompt_does_not_reintroduce_macro_reference_aliases():
    _repo, planner, cfg, state = await _resume_fixture()
    await novel_plan_volume_node(state, cfg)
    primary = planner.prompts[0].split("\n[Planning Reference Catalog]\n", 1)[0]
    assert "payoff-internal-memo" not in primary
    assert "payoff-water-debt" not in primary
    assert "setup-seal" not in primary
