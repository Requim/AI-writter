"""审美证据、主线继承和正文信息隔离的专项回归。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from application.creative.author_style import compile_style, validate_profile_sources
from application.creative.artifacts import workspace
from application.creative.cast import validate_cast_binding
from application.creative.errors import CreativePause
from application.creative.evidence import validate_relay, validate_character_transition
from application.creative.lifecycle import validate_lifecycle
from application.creative.names import refill_name_pool
from application.creative.policy import choose_route
from application.creative.runtime import active_creative_rules
from infrastructure.llm.metering import unique_creative_rules
from service.value_objects.author_style import AuthorProfile, AuthorSample, StylePreference
from service.value_objects.creative import ArcDuty, CharacterNarrative
from tests.creative_fakes import CreativeRepositoryFake, creative_config
from tests.test_creative_rules import evidence


def style_fixture(count=1, size=20):
    novel = uuid4()
    samples, preferences = {}, []
    for index in range(count):
        sample_id = uuid4()
        samples[str(sample_id)] = AuthorSample(original_confirmed=True, original="原" * size, revision="改" * size,
            judgment="accepted", reason="偏爱克制", novel_id=novel).model_dump(mode="json")
        preferences.append(StylePreference(preference_id=str(index), aspect=str(index), value="克制", reason="作者明确选择",
            novel_id=novel, sample_ids=[sample_id], tasks=["prose"]))
    return str(novel), samples, AuthorProfile(name="本书档案", preferences=preferences)


def test_style_pair_limits_and_no_profile_fallback():
    novel, samples, profile = style_fixture(8, 600)
    result = compile_style(profile, samples, task="prose", novel_id=novel, genre="suspense")
    assert len(result["examples"]) <= 3
    assert sum(len(e["comparison"]) for e in result["examples"]) <= 4000
    assert not compile_style(None, {}, task="prose", novel_id=novel, genre="suspense")["learned"]


def test_book_exception_cannot_become_global_or_cross_book():
    novel, samples, profile = style_fixture()
    assert not compile_style(profile, samples, task="prose", novel_id=str(uuid4()), genre="suspense")["learned"]
    global_preference = profile.preferences[0].model_copy(update={"scope": "global", "explicit_scope": True})
    with pytest.raises(ValueError, match="全局"):
        validate_profile_sources(profile.model_copy(update={"preferences": [global_preference]}), samples)


def test_factual_revision_is_not_style_evidence():
    _, samples, profile = style_fixture()
    samples[next(iter(samples))]["category"] = "fact_correction"
    with pytest.raises(ValueError, match="事实修正"):
        validate_profile_sources(profile, samples)


def test_hard_conflict_pauses_instead_of_silently_choosing():
    novel, samples, profile = style_fixture()
    one = profile.preferences[0].model_copy(update={"strength": "hard"})
    two = one.model_copy(update={"preference_id": "other", "value": "直给"})
    profile = profile.model_copy(update={"preferences": [one, two]})
    with pytest.raises(CreativePause, match="冲突"):
        compile_style(profile, samples, task="prose", novel_id=novel, genre="suspense")


def test_nested_prompt_rules_are_injected_only_once():
    token = active_creative_rules.set("唯一作者对照")
    try:
        payload = unique_creative_rules({"messages": [
            {"role": "system", "content": "风格唯一作者对照"},
            {"role": "user", "content": "正文唯一作者对照唯一作者对照"},
        ]}, "openai")
        assert str(payload).count("唯一作者对照") == 1
        reader = {"messages": [{"role": "user", "content": "只看正文"}]}
        assert unique_creative_rules(reader, "openai") == reader
    finally:
        active_creative_rules.reset(token)


def test_string_false_never_makes_a_route_feasible():
    assert choose_route([{"feasible": "false", "hard_constraints_pass": True}]) == {"status": "no_feasible_route"}


def test_supporting_promotion_keeps_identity_and_history():
    previous = CharacterNarrative(character_id="minor", name="路人", role="anonymous")
    promoted = previous.model_copy(update={"role": "core", "name": "许衡", "aliases": ["路人"], "evidence": [evidence()]})
    validate_character_transition(previous, promoted)
    with pytest.raises(ValueError, match="身份"):
        validate_character_transition(previous, promoted.model_copy(update={"character_id": "new"}))


def test_relay_requires_narrative_promise_and_four_bases():
    basis = dict(ability="既有能力", motivation="责任", reader_awareness="已登场", inheritance="继承任务", evidence=[evidence()])
    validate_relay("ensemble_relay", basis)
    with pytest.raises(CreativePause):
        validate_relay("stable", basis)
    with pytest.raises(CreativePause):
        validate_relay("ensemble_relay", {**basis, "inheritance": ""})


@pytest.mark.asyncio
async def test_fake_death_perception_does_not_change_canonical_life():
    repo = CreativeRepositoryFake()
    repo.canonical_life_status = AsyncMock(return_value="alive")
    work = await workspace(creative_config(repo, SimpleNamespace()))
    previous = CharacterNarrative(character_id="a", name="甲", life_status="alive")
    perceived = previous.model_copy(update={"perceived_life_status": "dead", "evidence": [evidence()]})
    await validate_lifecycle(work, previous, perceived, {}, perceived.evidence, 3)
    repo.canonical_life_status.assert_not_awaited()
    with pytest.raises(CreativePause, match="规范事实"):
        await validate_lifecycle(work, previous, perceived.model_copy(update={"life_status": "dead"}), {}, perceived.evidence, 3)


def test_exit_cannot_drop_an_unfinished_duty():
    previous = CharacterNarrative(character_id="a", name="甲", arc_duties=[ArcDuty(arc_id="main", function="drive")])
    with pytest.raises(CreativePause, match="职责"):
        validate_character_transition(previous, previous.model_copy(update={"narrative_status": "exited", "arc_duties": [], "evidence": [evidence()]}))


@pytest.mark.asyncio
async def test_name_pool_refill_is_stable_and_does_not_consume_models():
    repo = CreativeRepositoryFake()
    work = await workspace(creative_config(repo, SimpleNamespace()))
    state = {"total_outline": {}, "novel_type": "suspense"}
    first = await refill_name_pool(work, state, 1)
    repeated = await refill_name_pool(work, state, 1)
    pool = first["creative_brief"]["naming_policy"]["reserve_pool"]
    assert len(pool) == 24
    assert first == repeated
    assert len({c["name"] for c in pool}) == 24
    assert not repo.calls


def test_cast_cannot_bind_to_a_fabricated_arc():
    payload = {"characters": [{"character_id": "a", "arc_duties": [{"arc_id": "fake", "function": "drive"}]}], "slots": []}
    with pytest.raises(CreativePause, match="剧情弧"):
        validate_cast_binding(payload, {"arcs": [{"arc_id": "main"}]}, {"a": {"payload": {"role": "core"}}}, {})
