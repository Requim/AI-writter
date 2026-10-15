"""Real scene identity validation and bounded outline correction."""

from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.chapter_outline_node import _generate_outline
from application.errors import RetryableWorkflowError
from application.prompts.chapter_outline_prompts import build_chapter_outline_prompt
from application.runtime_observability import measured_node
from service.value_objects.creative import BudgetLimits
from service.value_objects.tactical_plan import TacticalWindow
from tests.test_tactical_workflow import _config, _outline, _plan, _state


def autonomous_state():
    state = _state(_plan())
    state["author_mode"] = "autonomous_v1"
    state["total_outline"].update(
        author_config={"author_mode": "autonomous_v1"},
        main_characters=[
            {"character_id": "stable-lead", "name": "沈墨", "role_type": "protagonist"},
            {"character_id": "stable-witness", "name": "何澄", "role_type": "supporting",
             "profile": {"secret": "unrevealed-author-secret"}},
        ],
    )
    state["tactical_window"] = TacticalWindow.from_dict({
        "schema_version": 1, "version": 1, "novel_plan_version": 1,
        "story_state_revision": 0, "source": "chapter_refresh",
        "start_chapter": 1, "end_chapter": 3, "volume_id": "v1",
        "window_objective": "核验来信",
        "beats": [{
            "chapter_number": number, "slot_ref": f"ch{number}",
            "tactical_goal": "核验证据", "approach": "向证人核实",
            "bridge_from_previous": "承接已知事实", "pressure_escalation": "窗口即将关闭",
            "exit_hook": "下一步行动明确", "pacing": "逐步推进",
        } for number in range(1, 4)],
    }).to_dict()
    return state


def autonomous_outline(character_id):
    raw = _outline()
    raw.update(
        state_delta="证据可信度改变",
        chapter_intent={"primary_function": "discovery", "expected_effect": "确认线索",
                        "subsequent_role": "为后续调查提供依据"},
    )
    raw["scenes"] = [{
        "function": "discovery", "purpose": "核验来信", "state_change": "确认线索",
        "character_ids": [character_id], "allowed_information": ["收到来信"],
        "action_requirements": ["核验笔迹"], "active_opposition": False,
    } for _ in range(2)]
    return raw


class OutlineProvider:
    def __init__(self, responses):
        self.responses = responses
        self.prompts = []

    async def structured_generate(self, prompt, schema, **kwargs):
        self.prompts.append(prompt)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


def config_for(provider):
    config = _config(provider, None)
    config["configurable"]["creative_repository"] = SimpleNamespace(
        get_session=AsyncMock(return_value={"id": "creative-session"}),
        latest=AsyncMock(return_value=None),
    )
    return config


def test_outline_prompt_exposes_exact_identity_mapping_outside_compact_story_bible():
    state = autonomous_state()
    state["total_outline"]["creative_brief"] = {"context": "背景" * 6000}
    prompt = build_chapter_outline_prompt(
        1, "suspense", "雨夜回信", state["total_outline"], "",
        schema_version=5,
    )
    assert "stable-lead" in prompt and "stable-witness" in prompt
    block = prompt.split("【可引用的既有人物ID】\n", 1)[1].split("\n【", 1)[0]
    assert json.loads(block) == [
        {"character_id": "stable-lead", "name": "沈墨", "role_type": "protagonist"},
        {"character_id": "stable-witness", "name": "何澄", "role_type": "supporting"},
    ]


@pytest.mark.asyncio
async def test_invalid_scene_identity_is_corrected_using_actual_validation_error():
    provider = OutlineProvider([
        autonomous_outline("invented-person"), autonomous_outline("stable-lead"),
    ])
    result = await _generate_outline(autonomous_state(), config_for(provider), 1)
    assert result["scenes"][0]["character_ids"] == ["stable-lead"]
    assert len(provider.prompts) == 2
    assert "场景出场人物必须引用已准入的character_id" in provider.prompts[1]


@pytest.mark.asyncio
async def test_three_invalid_scene_identities_stop_without_a_fourth_request():
    provider = OutlineProvider([autonomous_outline("invented-person") for _ in range(3)])
    with pytest.raises(RetryableWorkflowError, match="场景出场人物必须引用已准入"):
        await _generate_outline(autonomous_state(), config_for(provider), 1)
    assert len(provider.prompts) == 3


@pytest.mark.asyncio
async def test_provider_value_error_is_not_misclassified_as_outline_contract_error():
    provider = OutlineProvider([ValueError("provider configuration unavailable")])
    with pytest.raises(ValueError, match="provider configuration unavailable"):
        await _generate_outline(autonomous_state(), config_for(provider), 1)
    assert len(provider.prompts) == 1


@pytest.mark.asyncio
async def test_measured_outline_restore_keeps_old_snapshot_and_supplies_current_identities():
    state = autonomous_state()
    state["creative_session_id"] = "creative-session"
    state["prompt_snapshot"] = {
        "chapter/autonomous_outline.txt": "FROZEN_LEGACY_RULE\n$story_bible",
    }
    original_snapshot = deepcopy(state["prompt_snapshot"])
    provider = OutlineProvider([autonomous_outline("stable-lead")])
    config = config_for(provider)
    config["configurable"]["creative_repository"].get_session = AsyncMock(return_value={
        "id": "creative-session", "config": {}, "stage": "writing",
        "limits": BudgetLimits().resolved(3),
    })
    config["configurable"]["creative_repository"].require_enabled = AsyncMock()

    async def generation(state, config):
        return await _generate_outline(state, config, 1)

    result = await measured_node("chapter_outline_node", generation)(state, config)
    assert result["scenes"][0]["character_ids"] == ["stable-lead"]
    assert "FROZEN_LEGACY_RULE" in provider.prompts[0]
    assert "stable-lead" in provider.prompts[0] and "stable-witness" in provider.prompts[0]
    assert state["prompt_snapshot"] == original_snapshot
