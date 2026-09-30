"""归档正文证据及人物生命周期规则。"""

import hashlib
from typing import Any

from application.creative.errors import CreativePause
from service.value_objects.creative import CharacterNarrative, Foreshadow, TextEvidence


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def verify_evidence(evidence: TextEvidence, chapter: dict[str, Any]) -> None:
    """验证小说范围内已归档章节的版本、哈希及精确字符位置。"""
    if chapter.get("status") != "completed":
        raise ValueError("计划或草稿不能作为已发生事实的证据")
    expected = (str(evidence.chapter_id), evidence.chapter_version, evidence.chapter_number)
    actual = (str(chapter["id"]), chapter["version"], chapter["chapter_index"] + 1)
    if actual != expected:
        raise ValueError("正文证据指向了不同章节版本")
    body = chapter.get("content") or ""
    if content_hash(body) != evidence.content_hash:
        raise ValueError("正文证据哈希已失效")
    if body[evidence.start:evidence.end] != evidence.quote:
        raise ValueError("正文中不存在所引用片段")


def validate_character_transition(
    previous: CharacterNarrative, current: CharacterNarrative,
) -> None:
    """稳定身份，禁止计划冒充事实以及无依据复活或丢失主线职责。"""
    if (previous.character_id, previous.story_entity_id) != (
        current.character_id, current.story_entity_id,
    ):
        raise ValueError("人物身份不能通过改名合并或更换")
    changed = previous.model_dump(exclude={"evidence"}) != current.model_dump(exclude={"evidence"})
    if changed and not current.evidence:
        raise ValueError("人物变化必须引用归档正文")
    if previous.life_status == "dead" and current.life_status != "dead":
        raise CreativePause("canon_conflict", "已确认死亡不能由传闻、假死或模型推测撤销")
    if current.narrative_status == "exited":
        previous_arcs = {d.arc_id for d in previous.arc_duties}
        if not previous_arcs.issubset({d.arc_id for d in current.arc_duties}):
            raise CreativePause("unfinished_duties", "退场不能删除历史主线职责")
        unfinished = [d for d in current.arc_duties if d.status in {"planned", "active"}]
        if unfinished:
            raise CreativePause("unfinished_duties", "退场前必须处理或转移未完成主线职责")
    old_aliases = set(previous.aliases) | {previous.name}
    if current.name != previous.name and not old_aliases.issubset(set(current.aliases)):
        raise ValueError("身份变化必须保留历史姓名与化名")


def validate_relay(mode: str, basis: dict[str, Any]) -> None:
    """群像接力需要四项依据，稳定主角模式不允许自动换中心。"""
    if mode != "ensemble_relay":
        raise CreativePause("narrative_promise", "稳定主角模式不允许主线中心接力")
    if any(not basis.get(key) for key in ("ability", "motivation", "reader_awareness", "inheritance")):
        raise CreativePause("unprepared_relay", "接力缺少能力、动机、读者认知或主线继承依据")
    if not basis.get("evidence"):
        raise ValueError("群像接力必须有正文证据")


def validate_foreshadow_transition(previous: Foreshadow, current: Foreshadow) -> None:
    order = ["planned", "seeded", "reinforced", "partial", "completed"]
    if previous.foreshadow_id != current.foreshadow_id:
        raise ValueError("伏笔标识不可更换")
    if previous.conceived_at != current.conceived_at or previous.origin != current.origin:
        raise ValueError("不得倒填伏笔构思时间或修改起源")
    if order.index(current.status) < order.index(previous.status):
        raise ValueError("伏笔实际状态不可倒退")
    if not set(e.model_dump_json() for e in previous.evidence).issubset(
        {e.model_dump_json() for e in current.evidence}
    ):
        raise ValueError("伏笔历史证据不可删除")
