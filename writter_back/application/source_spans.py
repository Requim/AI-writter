"""Server-owned paragraph positions for model-selected original-text evidence."""

import json

from application.prompts.template_loader import render_prompt


def source_catalog(content: str) -> list[dict]:
    catalog, offset = [], 0
    for line in content.splitlines(keepends=True):
        text = line.rstrip("\r\n")
        if text.strip():
            catalog.append({"id": f"p{len(catalog) + 1}", "text": text,
                "start": offset, "end": offset + len(text)})
        offset += len(line)
    return catalog


def source_span(row: dict, content: str) -> tuple[int, str] | None:
    if not {"evidence_start", "evidence_end"}.intersection(row):
        return None
    start, end = row.get("evidence_start"), row.get("evidence_end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise ValueError("正文段落引用必须给出起止ID")
    catalog = {item["id"]: item for item in source_catalog(content)}
    first, last = catalog.get(start), catalog.get(end)
    if first is None or last is None or first["start"] > last["start"]:
        raise ValueError("正文段落引用不存在或顺序错误")
    selected = content[first["start"]:last["end"]]
    quote = row.get("quote")
    if quote is None or quote == "":
        return first["start"], selected
    if not isinstance(quote, str):
        raise ValueError("正文引文必须是原文字符串")
    at = selected.find(quote)
    if at < 0 or selected.find(quote, at + 1) >= 0:
        raise ValueError("引文不存在于指定段落或不能唯一定位")
    return first["start"] + at, quote


def archive_evidence_prompt(content: str) -> str:
    catalog = [{"id": row["id"], "text": row["text"]} for row in source_catalog(content)]
    return render_prompt("creative/archived_evidence_v1.txt", include_active_rules=False,
        catalog=json.dumps(catalog, ensure_ascii=False))
