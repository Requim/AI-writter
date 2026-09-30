"""复用可信姓名词库，补池不调用模型、不消费实际登场状态。"""

from copy import deepcopy

from application.naming.service import build_candidate_pool


async def refill_name_pool(work, state, chapter):
    total = deepcopy(state.get("total_outline") or {})
    policy = total.setdefault("creative_brief", {}).setdefault("naming_policy", {})
    pool = policy.get("reserve_pool") or []
    if len(pool) >= 6:
        return total
    key = f"chapter:{chapter}"
    batch = await work.latest("name_batch", key)
    if batch is None:
        previous = await work.records("name_batch")
        excluded = [c["name"] for c in total.get("main_characters", []) if c.get("name")]
        excluded.extend(c["name"] for c in pool)
        excluded.extend(c["name"] for b in previous for c in b["payload"]["candidates"])
        candidates = build_candidate_pool(
            tenant_id=work.tenant_id, novel_id=work.novel_id, proposal_version=f"refill:{chapter}",
            prompt_version=state.get("prompt_version") or "autonomous_v1", count=24 - len(pool),
            excluded_names=excluded, genre_tag=state.get("novel_type"),
        )
        batch = await work.save("name_batch", key, {"candidates": [c.to_dict() for c in candidates]},
                                source="system", status="available")
    policy["reserve_pool"] = [*pool, *batch["payload"]["candidates"]]
    policy["reserve_batch_id"] = batch["id"]
    return total
