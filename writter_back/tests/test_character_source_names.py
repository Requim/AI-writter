"""Model-only provisional names must be aligned before plan and goal binding."""

from copy import deepcopy
import json

import pytest

from application.agents.character_design_node import character_design_node, character_design_review_node
from application.errors import RetryableWorkflowError
from application.goal_contract import compile_goal_contract
from tests.test_character_design_workflow import _CharacterLLM, _config, _model_design, _pool_from_prompt


PREMISE = "档案员陆澄发现父亲陆守潮的签名，决定追查旧账。"


class MappedNamesLLM(_CharacterLLM):
    def __init__(self, mutation=None):
        super().__init__()
        self.mutation = mutation

    async def structured_generate(self, prompt, _schema, **_kwargs):
        self.calls += 1
        if _schema == {"addresses": "array"}:
            if self.mutation == "json_mode" and "json" not in (
                prompt + (_kwargs.get("system_prompt") or "")
            ).lower():
                raise RuntimeError("JSON mode requires an explicit JSON instruction")
            characters = json.loads(prompt.split("ADOPTED_CHARACTERS:\n", 1)[1].split("\n\n", 1)[0])
            result = {"addresses": [{"character_id": role["character_id"],
                "address_system": f"正式称呼{role['name']}；熟人称其职务。"}
                for role in characters]}
            if self.mutation == "missing_address":
                result["addresses"].pop()
            if self.mutation == "extra_address_fields":
                result["addresses"][0]["name"] = "错误改名"
            if self.mutation == "old_address_name":
                result["addresses"][0]["address_system"] = "仍称陆澄为小陆"
            return result
        result = _model_design(_pool_from_prompt(prompt))
        result["core_roles"][1]["role_type"] = "core"
        for role, name in zip(result["core_roles"], ("陆澄", "陆守潮")):
            role["source_name_binding"] = {"name": name, "quote": PREMISE}
        if self.mutation == "relationship_names":
            result["relationships"][0]["dynamic"] = "陆澄追问陆守潮的签名。"
        if self.mutation == "address_names":
            result["core_roles"][0]["profile"]["address_system"] = "父亲称澄澄，街坊称小陆。"
            result["core_roles"][1]["profile"]["address_system"] = "街坊称陆叔，女儿称爸。"
        if self.mutation == "absent_quote":
            result["core_roles"][0]["source_name_binding"]["quote"] = "来源中不存在的句子陆澄"
        if self.mutation == "duplicate":
            result["core_roles"][1]["source_name_binding"]["name"] = "陆澄"
        if self.mutation == "unknown_name":
            result["core_roles"][0]["source_name_binding"]["name"] = "另一个人"
        return result


def source_state():
    return {"novel_type": "suspense", "workflow_schema_version": 4, "proposal_versions": {},
        "author_mode": "autonomous_v1", "creative_narrative_mode": "stable",
        "summary": "年轻档案员查清旧账，保全证据并付出代价。",
        "creative_brief": {"core_premise": PREMISE, "reader_promise": "陆澄在书内解决旧账。",
            "research_material": {"writing_guidance": [PREMISE], "status": "applied"}},
        "genre_strategy": {"plot_engine": "陆澄查账，陆守潮承担责任。"}}


@pytest.mark.asyncio
async def test_accepting_names_aligns_generated_sources_before_goal_compilation():
    state = source_state()
    original = deepcopy(state)
    llm = MappedNamesLLM()
    config = _config(llm, auto_mode=True)
    generated = await character_design_node(state, config)
    result = await character_design_review_node({**state, **generated.update}, config)
    names = {c["character_id"]: c["name"] for c in result.update["character_design"]["characters"]}
    brief = result.update["creative_brief"]
    assert brief["core_premise"] == f"档案员{names['lead-1']}发现父亲{names['lead-2']}的签名，决定追查旧账。"
    assert result.update["genre_strategy"]["plot_engine"] == f"{names['lead-1']}查账，{names['lead-2']}承担责任。"
    assert brief["research_material"] == original["creative_brief"]["research_material"]
    assert state == original
    bound_state = {**state, **result.update, "novel_plan": {"version": 1,
        "scale": {"target_chapters": 1, "target_total_words": 3000},
        "chapter_slots": [{"chapter_number": 1, "must_happen": ["核对原件"]}]}}
    contract = compile_goal_contract(bound_state)
    assert contract["source"]["brief"]["core_premise"] == brief["core_premise"]
    assert result.update["character_design"]["characters"][0]["source_name_binding"]["quote"] == PREMISE


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["absent_quote", "duplicate", "unknown_name"])
async def test_invalid_name_identity_evidence_is_rejected_before_adoption(mutation):
    llm = MappedNamesLLM(mutation)
    with pytest.raises(RetryableWorkflowError):
        await character_design_node(source_state(), _config(llm, auto_mode=True))
    assert llm.calls == 3


@pytest.mark.asyncio
async def test_user_named_character_cannot_be_silently_replaced_by_generated_candidate():
    state = source_state()
    state["summary"] = "陆澄查清旧账。"
    llm = MappedNamesLLM()
    with pytest.raises(RetryableWorkflowError):
        await character_design_node(state, _config(llm, auto_mode=True))


@pytest.mark.asyncio
async def test_accepted_relationship_prose_uses_adopted_names_without_changing_identity():
    state = source_state()
    config = _config(MappedNamesLLM("relationship_names"), auto_mode=True)
    generated = await character_design_node(state, config)
    result = await character_design_review_node({**state, **generated.update}, config)
    design = result.update["character_design"]
    names = {c["character_id"]: c["name"] for c in design["characters"]}
    relation = design["relationships"][0]
    assert relation["dynamic"] == f"{names['lead-1']}追问{names['lead-2']}的签名。"
    assert relation["source_character_id"] == "lead-1"
    assert relation["target_character_id"] == "lead-2"


@pytest.mark.asyncio
async def test_generated_address_forms_are_reconciled_after_official_name_selection():
    state = source_state()
    config = _config(MappedNamesLLM("address_names"), auto_mode=True)
    generated = await character_design_node(state, config)
    before = deepcopy(generated.update["pending_proposal"]["payload"])
    result = await character_design_review_node({**state, **generated.update}, config)
    characters = result.update["character_design"]["characters"]
    assert all(role["profile"]["address_system"] == f"正式称呼{role['name']}；熟人称其职务。"
        for role in characters)
    lead = characters[0]
    assert lead["character_id"] == "lead-1"
    assert lead["profile"]["secret"] == before["core_roles"][0]["profile"]["secret"]
    assert lead["source_name_binding"]["quote"] == PREMISE
    assert "小陆" not in str(characters)
    assert state == source_state()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_address", "extra_address_fields", "old_address_name"])
async def test_address_reconciliation_cannot_change_identity_or_keep_replaced_names(mutation):
    state = source_state()
    config = _config(MappedNamesLLM(mutation), auto_mode=True)
    generated = await character_design_node(state, config)
    with pytest.raises(RetryableWorkflowError):
        await character_design_review_node({**state, **generated.update}, config)


@pytest.mark.asyncio
async def test_address_request_satisfies_provider_json_mode_without_rewriting_saved_prompt():
    state = source_state()
    config = _config(MappedNamesLLM("json_mode"), auto_mode=True)
    generated = await character_design_node(state, config)
    result = await character_design_review_node({**state, **generated.update}, config)
    assert result.goto == "title_node"
    assert len(result.update["character_design"]["characters"]) == 6
