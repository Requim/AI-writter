"""Persisted task recovery and explicit cancellation exercise the real service."""

import asyncio
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest


class Jobs:
    def __init__(self):
        self.value = {
            "id": str(uuid4()), "conversation_id": str(uuid4()), "message_id": str(uuid4()),
            "status": "queued", "content": "", "sources": [], "error": None,
            "request": {"text": "写雨夜", "intent": "discuss", "reference_ids": []},
            "snapshot": {"context": "硬设定", "sources": [], "history": []},
            "intent": "discuss", "chapter_index": None,
        }

    async def job(self, *args, **kwargs):
        return dict(self.value)

    async def update_job(self, *args, **fields):
        self.value.update(fields)
        return dict(self.value)


class Quota:
    def __init__(self):
        self.operations = set()

    async def reserve(self, context, run_id, operation, *args):
        self.operations.add((run_id, operation))


class Model:
    def __init__(self, fail=False):
        self.fail = fail

    async def stream_text(self, *args, **kwargs):
        yield "雨停了。"
        if self.fail:
            raise RuntimeError("provider unavailable")
        yield "他推开门。"


class Orchestrator:
    def __init__(self, model):
        self.model = model

    @asynccontextmanager
    async def exclusive_operation(self, *args):
        yield

    def _get_llm_instance(self):
        return self.model


def make_service(fail=False):
    try:
        service_class = importlib.import_module("application.workbench.service").WorkbenchService
    except ModuleNotFoundError:
        pytest.fail("Persistent workbench generation has not been implemented")
    repo, quota = Jobs(), Quota()
    service = service_class(repo, None, Orchestrator(Model(fail)), quota, None)
    context = SimpleNamespace(tenant_id=uuid4(), user_id=uuid4())
    return service, repo, quota, context


@pytest.mark.asyncio
async def test_job_stream_persists_reply_and_completes():
    service, repo, quota, context = make_service()
    await service.run_job(context, str(uuid4()), repo.value["id"])
    assert repo.value["status"] == "completed"
    assert repo.value["content"] == "雨停了。他推开门。"
    assert len(quota.operations) == 1


@pytest.mark.asyncio
async def test_oversized_reply_stops_and_preserves_asset_sized_partial():
    service, repo, quota, context = make_service()
    class OversizedModel:
        async def stream_text(self, *args, **kwargs):
            yield "雨" * 99999
            yield "停了。"
    service.orchestrator.model = OversizedModel()
    await service.run_job(context, str(uuid4()), repo.value["id"])
    assert repo.value["status"] == "failed"
    assert len(repo.value["content"]) == 100000
    assert repo.value["content"].endswith("停")
    assert "上限" in repo.value["error"]
    assert len(quota.operations) == 1


@pytest.mark.asyncio
async def test_provider_failure_preserves_partial_output_and_retry_quota_identity():
    service, repo, quota, context = make_service(fail=True)
    novel = str(uuid4())
    await service.run_job(context, novel, repo.value["id"])
    assert repo.value["status"] == "failed"
    assert repo.value["content"] == "雨停了。"
    service.orchestrator.model = Model()
    await service.run_job(context, novel, repo.value["id"])
    assert repo.value["status"] == "completed"
    assert repo.value["content"] == "雨停了。他推开门。"
    assert len(quota.operations) == 1


@pytest.mark.asyncio
async def test_cancelled_job_keeps_output_as_stopped():
    service, repo, quota, context = make_service()
    class WaitingModel:
        async def stream_text(self, *args, **kwargs):
            yield "已写正文"
            await asyncio.Event().wait()
    service.orchestrator.model = WaitingModel()
    task = asyncio.create_task(service.run_job(context, str(uuid4()), repo.value["id"]))
    for _ in range(100):
        if repo.value["status"] == "running":
            break
        await asyncio.sleep(0)
    task.cancel()
    await task
    assert repo.value["status"] == "stopped"


@pytest.mark.asyncio
async def test_targeted_rewrite_snapshot_contains_exact_chapter_text_and_version():
    from application.workbench.contracts import MessageInput
    from application.workbench.service import WorkbenchService
    from service.entities.chapter import Chapter
    chapter = Chapter(novel_id=uuid4(), title="旧约", chapter_index=0, version=7,
                      content="师父其实早已归还青玉剑。", status="completed")
    class Repository:
        async def basis(self, *args):
            return "basis"
        async def assets(self, *args):
            return []
        async def search(self, *args):
            return []
        async def conversation(self, *args):
            return {"messages": []}
    class Novels:
        async def find_by_id_with_chapters(self, *args):
            return SimpleNamespace(id=chapter.novel_id, chapters=[chapter], title="旧约", novel_type="suspense",
                                   total_outline=None, summary="一个失去记忆的师父回到故乡。")
    service = WorkbenchService(Repository(), Novels(), None, None, None)
    snapshot = await service.snapshot(SimpleNamespace(tenant_id=uuid4()), str(chapter.novel_id), str(uuid4()),
                                      MessageInput(text="保留结尾，改写前半段", intent="rewrite", target_chapter_id=chapter.id))
    assert chapter.content in snapshot["context"]
    assert "一个失去记忆的师父回到故乡。" in snapshot["context"]
    target = next(row for row in snapshot["sources"] if row["source_id"] == str(chapter.id))
    assert target["version"] == 7 and target["text"] == chapter.content
    assert (target["start"], target["end"]) == (0, len(chapter.content))


@pytest.mark.asyncio
async def test_invalid_adoption_target_is_rejected_before_quota_or_model():
    from application.workbench.contracts import AdoptInput
    from application.workbench.service import WorkbenchService
    class Repository:
        async def asset(self, *args):
            return {"version": 1, "kind": "chapter", "provenance": {}, "review": None, "title": "候选", "content": "正文"}
        async def basis(self, *args):
            return "basis"
    class Novels:
        async def find_by_id_with_chapters(self, *args):
            return SimpleNamespace(chapters=[])
    quota = Quota()
    service = WorkbenchService(Repository(), Novels(), Orchestrator(Model()), quota, None)
    with pytest.raises(LookupError, match="目标"):
        await service.adopt(SimpleNamespace(tenant_id=uuid4()), str(uuid4()), str(uuid4()),
                            AdoptInput(expected_version=1, acceptance="unreviewed", target_chapter_id=uuid4(), expected_chapter_version=1))
    assert not quota.operations
