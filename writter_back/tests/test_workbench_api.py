"""Real HTTP, quota and PostgreSQL adoption; only the external provider is controlled."""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from application.workbench.service import WorkbenchService
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.database.models import QuotaLedgerModel
from infrastructure.database.workbench_repository import WorkbenchRepository
from infrastructure.memory.postgres_memory import PostgresMemoryAdapter


class ControlledProvider:
    def __init__(self):
        self.stream_calls = self.structured_calls = 0

    async def stream_text(self, *args, **kwargs):
        self.stream_calls += 1
        yield "师父归还青玉剑。"
        yield "他离开了车站。"

    async def structured_generate(self, prompt, schema, **kwargs):
        self.structured_calls += 1
        if "summary" in schema:
            return {"summary": "师父还剑后离开。"}
        return {"timeline": [], "characters": [], "open_conflicts": [], "foreshadowing": [],
                "immutable_facts": ["青玉剑已经归还"], "last_transition": "师父离开车站"}


@pytest_asyncio.fixture
async def api_workbench(repository, tenant_context, sample_novel, async_client, monkeypatch):
    from api.main import app
    await repository.save(str(tenant_context.tenant_id), sample_novel)
    memory = PostgresMemoryAdapter("", repository.async_session)
    quota = QuotaService(IdentityRepository(repository.async_session))
    orchestrator = NovelOrchestrator(repository, memory, {}, quota_service=quota)
    provider = ControlledProvider()
    orchestrator._llm_instance = provider
    service = WorkbenchService(WorkbenchRepository(repository.async_session), repository, orchestrator, quota, memory)
    monkeypatch.setattr(app.state, "workbench_service", service, raising=False)
    yield async_client, service, provider, f"/api/v1/novels/{sample_novel.id}/workbench"
    await service.aclose()
    await orchestrator.aclose()


@pytest.mark.asyncio
async def test_http_job_replay_sse_save_and_adoption_are_idempotent(api_workbench, repository, sample_novel, tenant_context):
    client, service, provider, base = api_workbench
    response = await client.post(base + "/conversations", json={"title": "正文"})
    assert response.status_code == 201
    conversation = response.json()["id"]
    url, command = base + f"/conversations/{conversation}/messages", {"text": "写第一章", "intent": "write", "reference_ids": []}
    submitted = await client.post(url, json=command, headers={"Idempotency-Key": "once"})
    assert submitted.status_code == 202
    job = submitted.json()
    await asyncio.gather(*list(service.tasks.values()))
    replay = await client.post(url, json=command, headers={"Idempotency-Key": "once"})
    assert replay.json()["id"] == job["id"] and provider.stream_calls == 1
    stream = await client.get(base + f"/jobs/{job['id']}/stream")
    assert "event: snapshot" in stream.text and '"status": "completed"' in stream.text
    assert "command_key" not in stream.text and '"snapshot"' not in stream.text
    detail = (await client.get(base + f"/conversations/{conversation}")).json()
    assert [row["role"] for row in detail["messages"]] == ["user", "assistant"]
    reply = next(row for row in detail["messages"] if row["role"] == "assistant")
    saved = await client.post(base + "/assets", json={
        "title": "归还", "kind": "chapter", "content": reply["content"], "source_message_id": reply["id"],
    })
    assert saved.status_code == 201
    assert (await repository.find_by_id_with_chapters(str(tenant_context.tenant_id), str(sample_novel.id))).chapters == []
    url = base + f"/assets/{saved.json()['id']}/adopt"
    command = {"expected_version": 1, "acceptance": "unreviewed"}
    first = await client.post(url, json=command)
    assert first.status_code == 200, first.text
    again = await client.post(url, json=command)
    assert again.json()["chapter_id"] == first.json()["chapter_id"]
    assert provider.structured_calls == 2
    async with repository.async_session() as session:
        assert await session.scalar(select(func.count()).select_from(QuotaLedgerModel)) == 2
    hits = (await client.get(base + "/search", params={"q": "青玉剑"})).json()["hits"]
    assert hits and all(row["source_type"] == "chapter" for row in hits)


@pytest.mark.asyncio
async def test_http_workbench_does_not_reveal_another_tenants_novel(api_workbench, other_tenant_context):
    from api.dependencies import get_tenant_context
    from api.main import app
    client, _, _, base = api_workbench
    app.dependency_overrides[get_tenant_context] = lambda: other_tenant_context
    for suffix in ("/overview", f"/conversations/{uuid4()}", "/search?q=青玉剑"):
        response = await client.get(base + suffix)
        assert response.status_code == 404
