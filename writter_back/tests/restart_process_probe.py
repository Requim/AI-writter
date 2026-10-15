"""Isolated, no-provider process probe for the real checkpoint/lease lifecycle."""

import asyncio
import json
import signal
import sys
from pathlib import Path
from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from api.routers.workflow_router import PreparedWorkflow, _start_stream_execution
from api.workflow_commands import ClaimedWorkflowCommand
from application.automatic_restart import AutomaticRestartService, remember_automatic_run
from application.orchestrator import NovelOrchestrator
from application.quota_service import QuotaService
from config import settings
from infrastructure.command_store.postgres_command_store import PostgresWorkflowCommandStore
from infrastructure.database.identity_repository import IdentityRepository
from infrastructure.database.repository import PostgresNovelRepository


class ProbeState(TypedDict):
    novel_id: str
    workflow_run_id: str
    workflow_schema_version: int
    automatic_recovery: dict
    probe_completed: bool


class ProbeOrchestrator(NovelOrchestrator):
    def _get_llm_instance(self):
        return None

    async def _ensure_workflow(self):
        if self._workflow is not None:
            return
        await super()._ensure_workflow()
        gate = Path(sys.argv[4])

        async def initialize(state):
            return {"automatic_recovery": {"attempts": {"revision": 2}}}

        async def complete(state):
            gate.with_suffix(".entered").touch()
            while not gate.exists():
                await asyncio.sleep(0.05)
            assert state["workflow_run_id"] == "process-probe-quota"
            assert state["automatic_recovery"] == {"attempts": {"revision": 2}}
            return {"probe_completed": True}

        graph = StateGraph(ProbeState)
        graph.add_node("initialize", initialize)
        graph.add_node("complete", complete)
        graph.add_edge(START, "initialize")
        graph.add_edge("initialize", "complete")
        graph.add_edge("complete", END)
        self._workflow = graph.compile(checkpointer=self._checkpointer)


async def main():
    assert settings.DATABASE_URL.rsplit("/", 1)[-1].endswith("_test")
    repository = PostgresNovelRepository(settings.DATABASE_URL)
    identity = IdentityRepository(repository.async_session)
    user = await identity.current_user(UUID(sys.argv[2]))
    context = await identity.get_tenant_context(user, UUID(sys.argv[1]))
    novel, gate = sys.argv[3], Path(sys.argv[4])
    store = PostgresWorkflowCommandStore(repository.async_session)
    orchestrator = ProbeOrchestrator(repository, None, {})
    recovery = AutomaticRestartService(store, repository, identity, orchestrator, QuotaService(identity))
    stopped = asyncio.Event()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stopped.set)
    try:
        if sys.argv[5] == "start":
            claim = await store.claim(str(context.tenant_id), novel, "probe-original", 300)
            store.bind(claim.lease_token)
            assert await orchestrator.try_start(context, novel)
            orchestrator.set_auto_mode(context, novel, True)
            prepared = PreparedWorkflow(
                {"novel_id": novel, "workflow_run_id": "process-probe-quota",
                 "workflow_schema_version": 2}, None, False, False,
                ClaimedWorkflowCommand("probe-original", claim.lease_token), True)
            await remember_automatic_run(store, context, prepared)
            channel, _ = _start_stream_execution(orchestrator, store, context, novel, prepared)
            channel.disconnect()
        else:
            assert await recovery.recover_once() == 1
            gate.with_suffix(".restored").touch()
        await stopped.wait()
    finally:
        await recovery.stop()
        await orchestrator.aclose()
        state = await repository.find_by_id(str(context.tenant_id), novel)
        print(json.dumps({"novel": str(state.id), "stopped": True}), flush=True)
        await store.aclose()
        await repository.aclose()


if __name__ == "__main__":
    asyncio.run(main())
