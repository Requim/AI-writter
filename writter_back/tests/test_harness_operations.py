"""P6运营策略、离线评估、变形测试和无正文指标边界。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from api.routers.workflow_router import _prepare_execution, WorkflowInvokeRequest
from api.routers.novel_router import rewrite_chapter
from application.harness_evaluation import evaluation_snapshot, evaluation_judge, run_evaluation
from application.fact_evaluation import evaluate_facts
from application.fact_gate_workflow import _cached
from application.runtime_metrics import summarize_events
from application.runtime_observability import measured_node
from config import settings
from api.main import app
from api.dependencies import get_tenant_context


@pytest.mark.asyncio
async def test_offline_corpus_has_no_failures():
    result = await run_evaluation(Path(__file__).parents[1] / 'evals' / 'fact_cases.json')
    assert result['cases'] == result['passed'] == 13
    assert result['provider_calls'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('surname', ['辛', '赵', '钱', '孙'])
@pytest.mark.parametrize('prefix', ['', '雨停了。'])
async def test_name_substitution_and_neutral_prefix_preserve_hard_conflicts(surname, prefix):
    snapshot = evaluation_snapshot(surname)
    content = prefix + surname + '家祖祠归陆家所有。'
    report = await evaluate_facts(snapshot, content, 'body', None)
    assert report.status == 'blocked'
    assert report.findings[0].actual_evidence.quote in content


@pytest.mark.asyncio
async def test_force_human_review_never_bypasses_hard_rules_or_uses_cached_pass(monkeypatch):
    snapshot = evaluation_snapshot()
    content = '辛家祖祠归辛家所有。'
    passed = await evaluate_facts(snapshot, content, 'body', evaluation_judge('valid', snapshot))
    assert passed.status == 'pass'
    monkeypatch.setattr(settings, 'FACT_REVIEW_MODE', 'human_only')
    judge = SimpleNamespace(structured_generate=AsyncMock())
    assert (await evaluate_facts(snapshot, content, 'body', judge)).status == 'unknown'
    assert (await evaluate_facts(snapshot, '辛家祖祠归陆家所有。', 'body', judge)).status == 'blocked'
    assert _cached({'fact_reports': {'body': passed.model_dump(mode='json')}}, snapshot, content, 'body') is None
    judge.structured_generate.assert_not_called()


@pytest.mark.asyncio
async def test_pause_rejects_generation_and_rewrite_before_claim(monkeypatch):
    monkeypatch.setattr(settings, 'WORKFLOW_GENERATION_PAUSED', True)
    context = SimpleNamespace(tenant_id=uuid4())
    store = SimpleNamespace(claim=AsyncMock())
    repo = SimpleNamespace(find_by_id=AsyncMock(return_value=SimpleNamespace()))
    with pytest.raises(HTTPException) as error:
        await _prepare_execution('novel', WorkflowInvokeRequest(input={}), 'key', context, None, repo, None, store)
    assert error.value.status_code == 503 and error.value.detail['code'] == 'generation_paused'
    with pytest.raises(HTTPException):
        await rewrite_chapter('novel', 'chapter', None, 'key', context, repo, store)
    store.claim.assert_not_called()


@pytest.mark.asyncio
async def test_node_measurement_preserves_result_and_omits_payload(monkeypatch):
    observed = []
    monkeypatch.setattr('application.runtime_observability.emit_workflow_event', lambda *args: observed.append(args))
    async def node(state, config):
        return {'secret_draft': state['secret_draft']}
    result = await measured_node('test_node', node)({'secret_draft': 'private-content'}, {})
    assert result == {'secret_draft': 'private-content'}
    assert observed[0][1]['duration_seconds'] >= 0
    assert 'private-content' not in json.dumps(observed)


def test_metrics_count_retries_reviews_and_duration_without_text():
    result = summarize_events([{'type': 'status', 'node': 'writer', 'data': {'status': 'measurement', 'duration_seconds': 2.0}},
        {'type': 'status', 'data': {'status': 'retrying', 'text': 'private'}},
        {'type': 'interrupt', 'data': {'interrupts': [{'action': 'fact_review_required', 'proposal': {'payload': {'report': {'status': 'blocked'}}}}]}}])
    assert result['counts']['automatic_retries'] == result['counts']['fact_blocked'] == 1
    assert result['node_duration_seconds']['writer']['mean'] == 2.0
    assert 'private' not in json.dumps(result)


@pytest.mark.asyncio
async def test_measurement_failure_does_not_replace_node_result(monkeypatch):
    def fail(*args):
        raise RuntimeError('synthetic telemetry outage')
    monkeypatch.setattr('application.runtime_observability.emit_workflow_event', fail)
    async def node(state):
        return {'completed': True}
    assert await measured_node('test', node)({}) == {'completed': True}


@pytest.mark.asyncio
async def test_metrics_api_is_tenant_scoped(async_client, repository, tenant_context, sample_novel, other_tenant_context):
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    response = await async_client.get(f'/api/v1/workflows/{sample_novel.id}/metrics')
    assert response.status_code == 200
    assert response.json()['counts']['events'] == 0
    assert response.json()['fact_review_mode'] == 'standard'
    assert response.json()['truncated'] is False
    assert (await async_client.get('/api/v1/workflows/not-a-uuid/metrics')).status_code == 404
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    assert (await async_client.get(f'/api/v1/workflows/{sample_novel.id}/metrics')).status_code == 404
