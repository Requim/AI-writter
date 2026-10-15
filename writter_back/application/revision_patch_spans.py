"""Resolve local edits from existing immutable paragraph positions."""

import json

from application.errors import RetryableWorkflowError
from application.prompts.template_loader import render_prompt
from application.source_spans import source_catalog, source_span


def local_patch_prompt(content: str) -> str:
    catalog = [{"id": item["id"], "text": item["text"]} for item in source_catalog(content)]
    return render_prompt("revision/patch_spans.txt", include_active_rules=False,
        catalog=json.dumps(catalog, ensure_ascii=False))


def resolve_local_patch(payload: object, content: str) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("edits"), list):
        raise RetryableWorkflowError("局部修改范围无法验证")
    edits = []
    for raw in payload["edits"]:
        if not isinstance(raw, dict):
            raise RetryableWorkflowError("局部修改范围无法验证")
        try:
            selected = source_span({key: raw[key] for key in ("evidence_start", "evidence_end") if key in raw}, content)
        except ValueError:
            raise RetryableWorkflowError("局部修改段落引用无效") from None
        if selected is None or ("anchor" in raw and raw["anchor"] != selected[1]):
            raise RetryableWorkflowError("局部修改段落引用无效")
        edits.append({**raw, "anchor": selected[1]})
    return {**payload, "edits": edits}
