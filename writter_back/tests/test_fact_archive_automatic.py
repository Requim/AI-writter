from types import SimpleNamespace

import pytest

from application.fact_archive_guard import archive_fact_guard
from application.fact_evaluation import evaluate_facts
from tests.test_fact_gate import config, judge, setup_gate


@pytest.mark.asyncio
async def test_archive_callback_allows_partial_unknown_in_automatic_mode():
    value, content = setup_gate(), "他推开门。"
    report = (await evaluate_facts(value, content, "body", judge(value))).model_copy(
        update={"status": "unknown", "coverage": "partial", "findings": (), "reasons": ("证据覆盖不完整",)}
    )
    store = config(value)["configurable"]["story_fact_repository"]
    guard = archive_fact_guard(
        store, str(value.tenant_id), str(value.novel_id), value, report, None,
        allow_partial_automatic=True,
    )
    await guard(object(), SimpleNamespace(chapter_index=0, content=content))
    assert store.assert_constraints_current.await_count == 1
