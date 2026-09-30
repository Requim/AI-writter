"""内存创作仓储用于故障注入，不代替PostgreSQL事务验收。"""

from copy import deepcopy
from uuid import uuid4

from application.creative.errors import CreativeConflict
from infrastructure.database.creative_repository import increment_budget
from service.value_objects.creative import AuthorConfiguration, BudgetLimits


class CreativeRepositoryFake:
    def __init__(self, chapters=6):
        self.rows, self.archived, self.calls = [], [], []
        self.session = {
            "id": str(uuid4()), "config": AuthorConfiguration().model_dump(mode="json"),
            "limits": BudgetLimits().resolved(chapters), "counters": {}, "version": 1, "stage": "writing",
        }

    async def get_session(self, tenant, novel):
        return deepcopy(self.session)

    async def require_enabled(self, tenant):
        return None

    async def records(self, tenant, novel, kind=None):
        return deepcopy([r for r in self.rows if kind is None or r["kind"] == kind])

    async def latest(self, tenant, novel, kind, key):
        rows = [r for r in self.rows if r["kind"] == kind and r["key"] == key]
        return deepcopy(rows[-1]) if rows else None

    async def put(self, tenant, novel, record, *, expected_version, idempotency_key):
        previous = await self.latest(tenant, novel, record.kind, record.key)
        replay = next((r for r in self.rows if r["idempotency_key"] == idempotency_key), None)
        payload = record.model_dump(mode="json")
        if replay:
            if any(replay[k] != value for k, value in payload.items()):
                raise CreativeConflict("重复命令内容不一致")
            return deepcopy(replay)
        if (previous["version"] if previous else 0) != expected_version:
            raise CreativeConflict("陈旧版本")
        row = {**payload, "version": expected_version + 1, "id": str(uuid4()), "idempotency_key": idempotency_key}
        self.rows.append(row)
        return deepcopy(row)

    async def chapters(self, tenant, novel, through=None):
        return deepcopy([c for c in self.archived if through is None or c["chapter_index"] < through])

    async def reserve(self, tenant, novel, bucket, stage):
        self.session["counters"] = increment_budget(self.session["limits"], self.session["counters"], bucket)
        self.calls.append({"id": str(uuid4()), "status": "unknown"})
        return self.calls[-1]["id"]

    async def finish_request(self, tenant, novel, request_id, usage):
        next(r for r in self.calls if r["id"] == request_id)["status"] = "completed"

    async def advance(self, tenant, novel, stage, status="running"):
        self.session.update(stage=stage, status=status, version=self.session["version"] + 1)


def creative_config(repository, llm):
    return {"configurable": {
        "tenant_id": str(uuid4()), "novel_id": str(uuid4()), "creative_repository": repository,
        "llm_config": {"llm_instance": llm},
    }}
