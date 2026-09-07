"""归档事务内校验实际待写正文，不信任质量接受或旧事实报告。"""

from typing import Any

from application.fact_deterministic import deterministic_report
from application.story_facts import source_digest, validate_assertions
from service.value_objects.chapter_constraints import ChapterConstraintSet
from service.value_objects.fact_gate import FactGateBlockedError, FactGateReport


def verify_fact_receipt(snapshot: ChapterConstraintSet, report: FactGateReport, content: str,
                        acknowledgement: dict[str, Any] | None = None) -> None:
    """必须匹配稿件、作用域、规则和版本；人工确认也不能放过确定性硬冲突。"""
    if (report.tenant_id, report.novel_id, report.chapter_number, report.snapshot_digest, report.artifact_hash) != (
        snapshot.tenant_id, snapshot.novel_id, snapshot.chapter_number, snapshot.digest, source_digest(content),
    ):
        raise FactGateBlockedError("事实回执已失效，必须重新审校")
    if deterministic_report(snapshot, content, report.artifact_kind).status == "blocked" or report.status == "blocked":
        raise FactGateBlockedError("存在明确事实冲突，不能归档或接受")
    if any(item.severity == "hard_conflict" for item in report.findings):
        raise FactGateBlockedError("事实回执包含硬冲突")
    if report.status == "pass":
        checked = validate_assertions(list(report.assertions), list(snapshot.fact_heads), draft=content)
        if report.coverage != "complete" or report.findings or report.reasons or checked.status != "pass":
            raise FactGateBlockedError("事实回执不完整，不能判定通过")
        return
    ack = acknowledgement or {}
    if ack.get("report_digest") != report.digest or not ack.get("reviewed_by") or not ack.get("proposal_id"):
        raise FactGateBlockedError("未知事实结论需要针对当前证据单独人工确认")


def archive_fact_guard(store: Any, tenant_id: str, novel_id: str, snapshot: ChapterConstraintSet,
                       report: FactGateReport, acknowledgement: dict[str, Any] | None) -> Any:
    """构造在章节仓储同一事务和小说锁内执行的复验回调。"""
    async def guard(session: Any, chapter: Any) -> None:
        if report.artifact_kind != "body" or report.chapter_number != chapter.chapter_index + 1:
            raise FactGateBlockedError("归档事实回执章节或稿件类型不匹配")
        verify_fact_receipt(snapshot, report, chapter.content, acknowledgement)
        await store.assert_constraints_current(session, tenant_id, novel_id, chapter.chapter_index + 1, snapshot)
    return guard
