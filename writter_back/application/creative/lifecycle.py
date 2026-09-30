"""人物晋升、身份、生死、退场与接力的归档证据门禁。"""

from application.creative.errors import CreativePause
from application.creative.evidence import validate_relay


async def validate_lifecycle(work, previous, current, change, proofs, completed):
    """模型只能提出变化；规范生死、身份和主线承诺仍由规则复验。"""
    if previous.life_status != current.life_status:
        confirmed = await work.repository.canonical_life_status(
            work.tenant_id, work.novel_id, str(current.story_entity_id), completed,
        )
        if confirmed != current.life_status:
            raise CreativePause("life_fact_confirmation", "生死变化缺少规范事实确认，请走既有事实纠错流程")
    if previous.narrative_center != current.narrative_center:
        selection = await work.latest("selection", "accepted")
        basis = {**(change.get("relay_basis") or {}), "evidence": [p.model_dump(mode="json") for p in proofs]}
        validate_relay(selection["payload"]["narrative_mode"], basis)
    cards = {r["key"]: r for r in await work.records("character")}
    for duty in current.arc_duties:
        if duty.status == "transferred" and (not duty.successor_id or duty.successor_id not in cards or duty.successor_id == current.character_id):
            raise CreativePause("duty_successor", "职责转移必须指向另一个已准入身份")
    if current.narrative_status == "exited":
        await _check_open_threads(work, current)


async def _check_open_threads(work, current):
    latest = {r["key"]: r for r in await work.records("foreshadow")}
    unfinished = [r for r in latest.values() if current.character_id in r["payload"].get("character_ids", [])
                  and r["status"] != "completed" and not r["payload"].get("resolution")]
    if any(len(r["payload"].get("character_ids", [])) < 2 for r in unfinished):
        raise CreativePause("orphaned_foreshadow", "退场前须为未完成伏笔保留其他承接人物或解释其收束")


def validate_center_updates(changes, characters):
    centers = {key for key, row in characters.items() if row["payload"].get("narrative_center")}
    for change in changes:
        if "narrative_center" not in change.get("changes", {}):
            continue
        if change["changes"]["narrative_center"]:
            centers.add(change["character_id"])
        else:
            centers.discard(change["character_id"])
    if characters and not centers:
        raise CreativePause("missing_story_center", "主线接力不能留下没有承接者的空档")
