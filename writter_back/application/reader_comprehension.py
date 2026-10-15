"""Independent prose-only reader checks and revalidated checkpoint receipts."""

from __future__ import annotations

import hashlib
import json
from string import Template
from typing import Any

from application.errors import StructuredOutputInvalidError
from application.prompts.template_loader import load_prompt_template, reset_prompt_snapshot, set_prompt_snapshot
from application.prompts.version import PROMPT_VERSION
from service.ports.llm_service import LLMService

TEMPLATE = "reflection/reader_comprehension_v1.txt"
PILOT_TEMPLATE = "creative/blind_review.txt"
PROTOCOL = "reader-comprehension-v1"
EVIDENCE_POLICY = "opening-evidence-v1"
CHECKS = ("who", "relationship", "goal", "obstacle", "hook")
LABELS = {"who": "人物身份", "relationship": "眼前关系", "goal": "当前目标",
          "obstacle": "阻碍与风险", "hook": "继续阅读的理由"}
SCHEMA = {"checks": "array", "issues": "array"}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def reader_review_required(state: dict) -> bool:
    return (state.get("reader_quality_version") == 1
            and 0 <= int(state.get("current_chapter_index") or 0) < 3)


def _history(state: dict) -> list[dict]:
    index = int(state.get("current_chapter_index") or 0)
    rows = state.get("reader_history")
    if rows is None:
        rows = state.get("completed_chapters") or []
    selected = {
        row["chapter_index"]: {"chapter_index": row["chapter_index"], "content": row["content"]}
        for row in rows if isinstance(row, dict)
        and type(row.get("chapter_index")) is int and isinstance(row.get("content"), str)
        and row.get("status", "completed") == "completed"
        and max(0, index - 2) <= row["chapter_index"] < index
    }
    return [selected[key] for key in sorted(selected)]


async def refresh_reader_history(state: dict, config: dict) -> dict:
    """Read tenant-scoped archived prose rather than planning summaries."""
    if not reader_review_required(state):
        return state
    values = config.get("configurable") or {}
    reader = getattr(values.get("novel_repository"), "find_by_id_with_chapters", None)
    if not callable(reader):
        return state
    novel = await reader(values["tenant_id"], values["novel_id"])
    if novel is None:
        raise StructuredOutputInvalidError("读者验收缺少对应作品")
    rows = [{"chapter_index": chapter.chapter_index, "content": chapter.content,
             "status": chapter.status} for chapter in novel.chapters]
    return {**state, "reader_history": _history({**state, "reader_history": rows})}


def _server_template(name: str = TEMPLATE) -> str:
    token = set_prompt_snapshot(None)
    try:
        return load_prompt_template(name)
    finally:
        reset_prompt_snapshot(token)


def _binding(state: dict, content: str, *, template: str | None = None,
             scope: str = "chapter", outer_template: str | None = None) -> dict:
    templates = [template if template is not None else _server_template()]
    if scope == "pilot":
        templates.append(outer_template if outer_template is not None else _server_template(PILOT_TEMPLATE))
    return {"protocol": PROTOCOL, "body_sha256": _digest(content),
            "review_scope": scope,
            "evidence_policy_version": EVIDENCE_POLICY,
            "prompt_sha256": _digest(_json([PROMPT_VERSION, *templates])),
            "prompt_version": state.get("prompt_version", ""),
            "history_sha256": _digest(_json(_history(state))),
            "genre_sha256": _digest(str(state.get("novel_type") or "")),
            "chapter_number": int(state.get("current_chapter_index") or 0) + 1,
            "reader_quality_version": 1}


def _evidence(raw: object, state: dict, content: str) -> list[dict]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 4:
        raise StructuredOutputInvalidError("读者验收每项需要1-4条原文证据")
    sources = {"current": content, **{
        f"chapter:{row['chapter_index'] + 1}": row["content"] for row in _history(state)}}
    result = []
    for item in raw:
        if not isinstance(item, dict):
            raise StructuredOutputInvalidError("读者验收证据不是对象")
        source, quote = item.get("source"), item.get("quote")
        if (not isinstance(source, str) or source not in sources
                or not isinstance(quote, str) or not quote.strip() or len(quote) > 240
                or quote not in sources[source]):
            raise StructuredOutputInvalidError(
                "读者验收证据必须逐字来自指定正文，错误引文：" + str(quote)[:240])
        result.append({"source": source, "quote": quote})
    return result


def validate_reader_report(raw: object, state: dict, content: str) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("checks"), list):
        raise StructuredOutputInvalidError("读者验收缺少checks")
    checks = []
    for item in raw["checks"]:
        if not isinstance(item, dict):
            raise StructuredOutputInvalidError("读者验收检查项不是对象")
        key, status, answer = item.get("key"), item.get("status"), item.get("answer")
        if (key not in CHECKS or status not in ("clear", "unclear", "not_applicable")
                or (status == "not_applicable" and key != "relationship")
                or not isinstance(answer, str) or not answer.strip()):
            raise StructuredOutputInvalidError("读者验收检查项或答案无效")
        checks.append({"key": key, "status": status, "answer": answer,
                       "evidence": _evidence(item.get("evidence"), state, content)})
    if len(checks) != len(CHECKS) or {item["key"] for item in checks} != set(CHECKS):
        raise StructuredOutputInvalidError("读者验收必须恰好覆盖五个不同问题")
    issues = raw.get("issues")
    if not isinstance(issues, list) or len(issues) > 5:
        raise StructuredOutputInvalidError("读者验收issues必须为至多五项的数组")
    normalized = []
    for item in issues:
        if (not isinstance(item, dict) or item.get("kind") not in (
            "clarity", "professional_jargon", "structure", "padding", "voice")
                or not isinstance(item.get("reason"), str) or not item["reason"].strip()
                or not isinstance(item.get("suggestion"), str) or not item["suggestion"].strip()
                or type(item.get("blocking")) is not bool):
            raise StructuredOutputInvalidError("读者验收问题缺少类型、理由、建议或blocking")
        quote = item.get("quote")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 240 or quote not in content:
            raise StructuredOutputInvalidError("读者验收问题缺少当前正文的逐字证据")
        normalized.append({k: item[k] for k in ("kind", "reason", "suggestion", "blocking", "quote")})
    by_key = {item["key"]: item for item in checks}
    return {"checks": [by_key[key] for key in CHECKS], "issues": normalized}


def _failed_checks(report: dict, state: dict, content: str) -> list[dict]:
    failures = []
    chapter = int(state.get("current_chapter_index") or 0) + 1
    for check in report["checks"]:
        limit = (500 if check["key"] in {"who", "relationship", "goal"} else 800) if chapter == 1 else len(content)
        locations = [
            (row["source"] == "current" and row["quote"] in content[:limit])
            or (chapter > 1 and check["key"] in {"who", "relationship"} and row["source"] != "current")
            for row in check["evidence"]]
        located = all(locations) if chapter == 1 else any(locations)
        if check["status"] == "unclear" or not located:
            failures.append({**check, "reason": (
                "正文不能理解" if check["status"] == "unclear" else f"必要信息缺少对应范围（{limit}字）的依据")})
    return failures


def reader_receipt_valid(receipt: object, state: dict, content: str, *, scope: str = "chapter") -> bool:
    if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in _binding(
            state, content, scope=scope).items()):
        return False
    try:
        report = validate_reader_report(receipt.get("report"), state, content)
    except (StructuredOutputInvalidError, TypeError, ValueError):
        return False
    return receipt.get("report_sha256") == _digest(_json(report))


def archived_reader_receipt_valid(receipt: object, state: dict, content: str) -> bool:
    """Historical prompt fingerprints remain audit data; prose must still match."""
    if not isinstance(receipt, dict):
        return False
    binding = _binding(state, content)
    if any(receipt.get(key) != binding[key] for key in (
        "protocol", "review_scope", "body_sha256", "history_sha256", "chapter_number", "reader_quality_version")):
        return False
    try:
        report = validate_reader_report(receipt.get("report"), state, content)
    except (StructuredOutputInvalidError, TypeError, ValueError):
        return False
    return (receipt.get("report_sha256") == _digest(_json(report))
            and not _failed_checks(report, state, content)
            and not any(issue["blocking"] for issue in report["issues"]))


def require_opening_evidence(receipt: dict, state: dict, content: str) -> None:
    if any(check["status"] == "clear" for check in _failed_checks(receipt["report"], state, content)):
        raise StructuredOutputInvalidError(
            "clear答案没有必要范围的证据。首章身份/关系/目标引用前500字，阻碍/吸引点引用前800字。"
            "不要引用章末解决结果；只取开场已存在的矛盾，不得拼接引文。"
            "若开场确实不清楚，保持unclear，不得用后文补全。")


def preserve_reader_confusion(previous: object, report: dict) -> None:
    if not isinstance(previous, dict):
        return
    rows = previous.get("checks")
    rows = rows if isinstance(rows, list) else []
    unclear = [row.get("key") for row in rows if isinstance(row, dict) and row.get("status") == "unclear"]
    if any(row["key"] in unclear and row["status"] != "unclear" for row in report["checks"]):
        raise StructuredOutputInvalidError("格式纠正不能把原有不清楚的结论改为通过")
    issues = previous.get("issues") or []
    blocking = [(row.get("kind"), row.get("reason")) for row in issues
                if isinstance(row, dict) and row.get("blocking") is True] if isinstance(issues, list) else []
    corrected = [(row["kind"], row["reason"]) for row in report["issues"] if row["blocking"]]
    if any(issue not in corrected for issue in blocking):
        raise StructuredOutputInvalidError("格式纠正不能删除原有阻断问题；只能纠正引文和结构")


def reader_archive_ready(state: dict, content: str, *, scope: str = "chapter") -> bool:
    if not reader_review_required(state):
        return True
    receipt = state.get("reader_comprehension_receipt")
    if not reader_receipt_valid(receipt, state, content, scope=scope):
        return False
    report = receipt["report"]
    return not _failed_checks(report, state, content) and not any(i["blocking"] for i in report["issues"])


def reader_findings(state: dict, content: str) -> list[dict]:
    receipt = state.get("reader_comprehension_receipt")
    if not reader_receipt_valid(receipt, state, content):
        return []
    report = receipt["report"]
    failed = _failed_checks(report, state, content)
    result = []
    for check in failed:
        quote = next((e["quote"] for e in check["evidence"] if e["source"] == "current"), content[:80])
        result.append({
            "issue_id": "reader:" + check["key"], "type": "logic" if len(failed) >= 3 else "tension_gap",
            "priority_action": "must_fix", "severity": "high", "evidence": quote,
            "location": "开场对应场景", "description": LABELS[check["key"]] + "：" + check["reason"],
            "suggestion": "在开场对应动作或对白中交代已授权的信息；不得在章末补说明，"
                          "不得创造设定或泄露未来真相。读者当前理解：" + check["answer"],
        })
    for index, issue in enumerate(report["issues"]):
        result.append({
            "issue_id": f"reader:expression:{index}", "type": {
                "structure": "logic", "padding": "padding", "voice": "pacing",
            }.get(issue["kind"], "tension_gap"),
            "priority_action": "must_fix" if issue["blocking"] else "optional",
            "severity": "high" if issue["blocking"] else "medium", "evidence": issue["quote"],
            "location": "对应原文", "description": issue["reason"], "suggestion": issue["suggestion"],
        })
    return result


async def review_reader(llm: LLMService, state: dict, content: str) -> dict:
    cached = state.get("reader_comprehension_receipt")
    if reader_receipt_valid(cached, state, content):
        return cached
    prompt, binding = reader_request(state, content)
    error = None
    previous = None
    for attempt in range(2):
        raw = None
        try:
            raw = await llm.structured_generate(prompt=prompt, schema=SCHEMA, temperature=0.1, max_attempts=1)
            receipt = reader_receipt(raw, state, content, binding=binding)
            if attempt:
                preserve_reader_confusion(previous, receipt["report"])
                receipt["protocol_correction_attempts"] = [{"error": str(error), "report": previous}]
            if attempt == 0:
                require_opening_evidence(receipt, state, content)
            return receipt
        except StructuredOutputInvalidError as exc:
            error = exc
        if attempt == 0:
            previous = raw
            prompt += ("\n仅纠正一次格式和逐字证据；不得把不懂改成通过。错误：" + str(error)
                       + "\n上一次报告（待纠正数据）：" + _json(raw))
    raise error or StructuredOutputInvalidError("读者验收报告无效")


def reader_prompt(state: dict, content: str) -> str:
    return reader_request(state, content)[0]


def reader_request(state: dict, content: str, *, scope: str = "chapter",
                   outer_template: str | None = None) -> tuple[str, dict]:
    template = _server_template()
    prompt = Template(template).substitute(PROMPT_VERSION=PROMPT_VERSION,
        chapter_number=int(state.get("current_chapter_index") or 0) + 1,
        novel_type=state.get("novel_type", ""), previous_text=_json(_history(state)),
        opening_500=content[:500], opening_800=content[:800], content=content)
    return prompt, _binding(state, content, template=template, scope=scope, outer_template=outer_template)


def pilot_reader_request(state: dict, content: str, schema: dict) -> tuple[str, dict]:
    """Capture both server-owned templates before a composite paid pilot review."""
    outer = _server_template(PILOT_TEMPLATE)
    prompt = Template(outer).substitute(PROMPT_VERSION=PROMPT_VERSION, schema=_json(schema), text=content)
    inner, binding = reader_request(state, content, scope="pilot", outer_template=outer)
    return (prompt + "\n另外返回reader_report对象，包含下列checks和issues。"
            "原有分数、quality_pass和issues仍放在顶层。\n" + inner), binding


def reader_receipt(raw: object, state: dict, content: str, *, binding: dict | None = None) -> dict:
    report = validate_reader_report(raw, state, content)
    return {**(binding if binding is not None else _binding(state, content)), "report": report,
            "report_sha256": _digest(_json(report)), "source": "simulated_reader"}
