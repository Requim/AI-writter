"""角色设计工作流、选择协议与旧数据兼容测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from application.agents.character_design_node import (
    character_design_node,
    character_design_review_node,
)
from application.agents.outline_generator_node import _prepare_outline, outline_generator_node
from application.errors import RetryableWorkflowError
from application.naming import load_source_entries


def _profile(index: int) -> dict[str, str]:
    return {
        "identity": f"身份{index}", "external_goal": f"外在目标{index}",
        "internal_lack": f"内在缺口{index}", "false_belief": f"错误信念{index}",
        "secret": f"秘密{index}", "abilities": f"能力{index}",
        "limitations": f"限制{index}", "moral_red_line": f"底线{index}",
        "speech_fingerprint": f"语言指纹{index}", "address_system": f"称谓{index}",
        "arc_direction": f"人物弧{index}",
    }


def _reference(candidate: dict, index: int) -> dict[str, str]:
    del index
    return {
        "surname": candidate["surname"], "source_id": candidate["source_id"],
    }


def _model_design(pool: list[dict]) -> dict:
    core = []
    for role_index, start in enumerate((0, 3), 1):
        core.append({
            "character_id": f"lead-{role_index}", "role_type": "protagonist",
            "profile": _profile(role_index),
            "name_candidates": [_reference(pool[start + offset], offset) for offset in range(3)],
            "recommended_candidate_index": 0,
        })
    supporting = [{
        "character_id": f"support-{index}", "role_type": "supporting",
        "profile": _profile(index + 2), "name_candidate": _reference(pool[index + 5], index),
    } for index in range(1, 5)]
    return {
        "core_roles": core, "supporting_characters": supporting,
        "relationships": [{
            "source_character_id": "lead-1", "target_character_id": "lead-2",
            "relationship_type": "盟友", "dynamic": "信任在秘密曝光后破裂",
        }],
    }


def _pool_from_prompt(prompt: str) -> list[dict]:
    block = prompt.split("【本次允许使用的姓名引用池】\n", 1)[1]
    return json.loads(block.split("\n\n【输出约束】", 1)[0])


class _CharacterLLM:
    def __init__(self, invalid_attempts: int = 0) -> None:
        self.invalid_attempts = invalid_attempts
        self.calls = 0

    async def structured_generate(self, prompt, _schema, **_kwargs):
        self.calls += 1
        result = _model_design(_pool_from_prompt(prompt))
        if self.calls <= self.invalid_attempts:
            result["core_roles"][0]["name_candidates"][0]["source_id"] = "unknown"
        return result


def _state() -> dict:
    return {
        "novel_type": "suspense", "workflow_schema_version": 4,
        "creative_brief": {"naming_preference": "当代江南，姓名克制清朗"},
        "proposal_versions": {},
    }


def _config(llm: _CharacterLLM, *, auto_mode: bool = False, repository=None) -> dict:
    return {"configurable": {
        "llm_config": {"llm_instance": llm}, "auto_mode": auto_mode,
        "tenant_id": "tenant-a", "novel_id": "novel-a", "novel_repository": repository,
    }}


@pytest.mark.asyncio
async def test_character_proposal_has_verified_candidates_and_reserve_pool() -> None:
    command = await character_design_node(_state(), _config(_CharacterLLM()))
    proposal = command.update["pending_proposal"]["payload"]
    source_index = {item.source_id: item for item in load_source_entries()}
    assert command.goto == "character_design_review_node"
    assert all(len(role["name_candidates"]) == 3 for role in proposal["core_roles"])
    assert len(proposal["naming_policy"]["reserve_pool"]) == 24
    candidate = proposal["core_roles"][0]["name_candidates"][0]
    assert candidate["source_quote"] == source_index[candidate["source_id"]].quote


@pytest.mark.asyncio
async def test_review_selects_current_candidate_and_accepts_custom_name() -> None:
    state = _state()
    generated = await character_design_node(state, _config(_CharacterLLM()))
    checkpoint = {**state, **generated.update}
    proposal = checkpoint["pending_proposal"]
    roles = proposal["payload"]["core_roles"]
    checkpoint["pending_proposal_decision"] = {
        "proposal_id": proposal["proposal_id"], "decision": "modify",
        "value": {
            "name_selections": {"lead-1": roles[0]["name_candidates"][1]["candidate_id"]},
            "custom_names": {"lead-2": "第五轻尘"},
        },
    }
    accepted = await character_design_review_node(checkpoint, _config(_CharacterLLM()))
    characters = {item["character_id"]: item for item in accepted.update["character_design"]["characters"]}
    assert characters["lead-1"]["name"] == roles[0]["name_candidates"][1]["name"]
    assert characters["lead-2"]["origin_type"] == "user_provided"
    assert "source_id" not in characters["lead-2"]


@pytest.mark.asyncio
async def test_invalid_model_naming_retries_twice_then_succeeds() -> None:
    llm = _CharacterLLM(invalid_attempts=2)
    command = await character_design_node(_state(), _config(llm, auto_mode=True))
    assert command.goto == "title_node"
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_three_invalid_model_results_return_retryable_error() -> None:
    llm = _CharacterLLM(invalid_attempts=3)
    with pytest.raises(RetryableWorkflowError, match="角色设计生成失败"):
        await character_design_node(_state(), _config(llm))


@pytest.mark.asyncio
async def test_existing_outline_backfills_character_design_without_llm() -> None:
    state = {
        **_state(), "character_design_return_to": "outline_node",
        "total_outline": {"main_characters": [{"姓名": "顾清扬", "性格": "谨慎", "目标": "查案"}]},
    }
    command = await character_design_node(state, _config(_CharacterLLM()))
    character = command.update["character_design"]["characters"][0]
    assert command.goto == "outline_node"
    assert character["name"] == "顾清扬"
    assert character["profile"]["external_goal"] == "查案"


@pytest.mark.asyncio
async def test_outline_routes_old_checkpoint_to_character_design_first() -> None:
    command = await outline_generator_node(
        {"novel_type": "suspense", "title": "旧案", "summary": "简介"},
        _config(_CharacterLLM()),
    )
    assert command.goto == "character_design_node"
    assert command.update["character_design_return_to"] == "outline_node"


def test_confirmed_characters_override_outline_model_names() -> None:
    characters = [{"character_id": f"role-{index}", "name": f"顾{index}"} for index in range(6)]
    state = {
        "title": "旧案", "summary": "简介", "creative_brief": {},
        "character_design": {"characters": characters, "naming_policy": {"reserve_pool": []}},
    }
    generated = {
        "story_background": "当代城市", "main_characters": [{"name": "错误姓名"}] * 6,
        "main_plot": {"opening": "收到线索"}, "writing_style": "冷峻克制",
        "total_chapters": 30,
        "volumes": [{"start_chapter": 1, "end_chapter": 30}],
    }
    outline = _prepare_outline(state, generated)
    assert outline["main_characters"] == characters
    assert outline["creative_brief"]["naming_policy"]["reserve_pool"] == []


@pytest.mark.asyncio
async def test_recent_twenty_novels_are_used_as_name_exclusions() -> None:
    repository = SimpleNamespace(find_all=AsyncMock(return_value=[]))
    command = await character_design_node(_state(), _config(_CharacterLLM(), repository=repository))
    assert command.goto == "character_design_review_node"
    repository.find_all.assert_awaited_once_with("tenant-a")
