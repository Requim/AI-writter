"""试用只作用于后续正文，不学习为跨书审美，不修改历史章节。"""

from application.creative.artifacts import json_text
from service.value_objects.creative import CreativeRecord


async def trial_rules(repository, tenant_id, novel_id, chapter):
    latest = {r["key"]: r for r in await repository.records(tenant_id, novel_id, "experiment")}
    selected = []
    for record in latest.values():
        value = record["payload"]
        if record["status"] not in {"model_supported_trial", "human_supported"}:
            continue
        start, end = value.get("trial_start"), value.get("trial_end")
        if start is None or chapter < start or (record["status"] != "human_supported" and chapter > end):
            continue
        selected.append({"factor": value["factor"], "source": record["status"], "experiment_id": record["id"]})
        key = f"{record['key']}:chapter:{chapter}"
        if not await repository.latest(tenant_id, novel_id, "adoption", key):
            await repository.put(tenant_id, novel_id, CreativeRecord(
                kind="adoption", key=key, payload=selected[-1], status=record["status"],
                source="system", input_versions={"experiment": record["version"]},
            ), expected_version=0, idempotency_key=f"adoption:{novel_id}:{key}")
    if not selected:
        return ""
    return "\n【本书后续章节的有限试用】" + json_text(selected) + "\n不得覆盖作者硬约束、人物事实、既定场景功能或本书审美，不重写历史正文。"
