"""结构性改纲接受前的职责、伏笔、读者承诺及输入版本复验。"""

from application.creative.artifacts import json_text
from application.creative.errors import CreativePause, CreativeConflict
from application.prompts.template_loader import render_prompt

KINDS = ("character", "foreshadow", "reader_state", "secret")


async def audit_replan(work, previous, proposed, proposal_id):
    latest = {(r["kind"], r["key"]): r for r in await work.records() if r["kind"] in KINDS}
    versions = {f"{kind}:{key}": row["version"] for (kind, key), row in latest.items()}
    key = f"replan_audit:{proposal_id}"
    saved = await work.latest("decision", key)
    if saved is None:
        result = await work.generate(render_prompt(
            "creative/replan_audit.txt", config=json_text(work.session["config"]),
            previous=json_text(previous), proposed=json_text(proposed), records=json_text(list(latest.values())),
        ), {"hard_settings_pass": "boolean", "responsibilities_pass": "boolean", "foreshadow_pass": "boolean",
            "reader_promises_pass": "boolean", "reason": "string", "change_mapping": "array"})
        saved = await work.save("decision", key, result, inputs=versions, status="reviewed")
    if saved["input_versions"] != versions:
        raise CreativeConflict("改纲评估所依据的人物、伏笔或读者版本已变化")
    fields = ("hard_settings_pass", "responsibilities_pass", "foreshadow_pass", "reader_promises_pass")
    if any(saved["payload"].get(field) is not True for field in fields):
        raise CreativePause("replan_contract", "改纲未通过承诺与硬设定复验：" + str(saved["payload"].get("reason", "")))
