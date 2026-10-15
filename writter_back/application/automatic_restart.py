"""Resume bounded, authorized automatic work from durable execution intent."""

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from config import settings
from service.ports.workflow_command_store import WorkflowCommandClaimStatus, WorkflowCommandStoreUnavailable

logger = logging.getLogger("uvicorn")


async def remember_automatic_run(store: Any, context: Any, prepared: Any) -> None:
    persist = getattr(store, "set_recovery", None)
    if not callable(persist) or not prepared.auto_mode:
        return
    deadline = prepared.deadline or datetime.now(timezone.utc) + timedelta(
        seconds=settings.WORKFLOW_BACKGROUND_TIMEOUT_SECONDS)
    intent = {"user_id": str(context.user_id), "restarts": 0,
              "deadline": deadline.isoformat(), "input_data": prepared.input_data,
              "resume_value": prepared.resume_value, "is_resume": prepared.is_resume}
    if not await persist(prepared.command.lease_token, intent):
        raise WorkflowCommandStoreUnavailable("Automatic recovery intent was not saved")


class AutomaticRestartService:
    def __init__(self, store: Any, repository: Any, identity: Any, orchestrator: Any, quota: Any):
        self.store, self.repository, self.identity = store, repository, identity
        self.orchestrator, self.quota = orchestrator, quota
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop(), name="automatic-restart")

    async def stop(self) -> None:
        self.store.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def _loop(self) -> None:
        while True:
            try:
                await self.recover_once()
            except Exception:
                logger.exception("Automatic restart scan failed")
            await asyncio.sleep(10)

    async def recover_once(self) -> int:
        await self.store.recover_expired()
        started = 0
        for candidate in await self.store.recovery_candidates():
            try:
                started += await self._restore(candidate)
            except Exception:
                logger.exception("Automatic restart failed for run %s", candidate["run_id"])
                await self.store.clear_recovery(UUID(candidate["run_id"]))
        return started

    async def _context(self, candidate: dict) -> Any:
        intent = candidate["recovery"]
        user = await self.identity.current_user(UUID(intent["user_id"]))
        if user is None or user.status != "active":
            return None
        context = await self.identity.get_tenant_context(user, UUID(candidate["tenant_id"]))
        return context if context and context.ai_enabled else None

    async def _restore(self, candidate: dict) -> int:
        if settings.WORKFLOW_GENERATION_PAUSED:
            return 0
        intent = candidate["recovery"]
        deadline = datetime.fromisoformat(intent["deadline"])
        if not deadline.tzinfo or deadline <= datetime.now(timezone.utc) or intent["restarts"] >= 3:
            await self.store.clear_recovery(UUID(candidate["run_id"]))
            return 0
        context = await self._context(candidate)
        if context is None:
            await self.store.clear_recovery(UUID(candidate["run_id"]))
            return 0
        novel = candidate["novel_id"]
        state = await self.orchestrator.get_public_state(context, novel)
        if state.get("has_interrupt") or state.get("interrupts"):
            await self.store.clear_recovery(UUID(candidate["run_id"]))
            return 0
        run_id = await self.orchestrator.get_workflow_run_id(context, novel)
        if run_id and not (state.get("next_nodes") or state.get("has_pending_checkpoint")):
            await self.store.clear_recovery(UUID(candidate["run_id"]))
            return 0
        command_id = f"restart:{candidate['run_id']}"
        claim = await self.store.claim(str(context.tenant_id), novel, command_id,
            (deadline - datetime.now(timezone.utc)).total_seconds(),
            expected_run_id=UUID(candidate["run_id"]))
        if claim.status != WorkflowCommandClaimStatus.ACQUIRED:
            return 0
        await self._start_claimed(candidate, context, command_id, claim.lease_token, deadline, state)
        return 1

    async def _start_claimed(
        self, candidate: dict, context: Any, command_id: str, token: str,
        deadline: datetime, state: dict,
    ) -> None:
        from api.routers import workflow_router as routes
        from api.workflow_commands import ClaimedWorkflowCommand
        intent, novel = candidate["recovery"], candidate["novel_id"]
        command: dict[str, Any] = {"retry": True, "_auto_mode": True}
        if state.get("has_interrupt") and intent.get("is_resume"):
            command = {"resume": intent.get("resume_value"), "_auto_mode": True}
        self.store.bind(token)
        try:
            prepared = await routes._prepare_execution(
                novel, routes.WorkflowInvokeRequest(command=command), command_id, context,
                self.orchestrator, self.repository, self.quota, self.store,
                background=True, claimed_command=ClaimedWorkflowCommand(command_id, token))
            if not await self.orchestrator.get_workflow_run_id(context, novel):
                if not intent.get("input_data"):
                    raise HTTPException(409, "No checkpoint or initial input for restart")
                prepared = replace(prepared, input_data=intent["input_data"], is_retry=False, is_resume=False)
            saved_checkpoint = bool(await self.orchestrator.get_workflow_run_id(context, novel))
            prepared = replace(prepared, deadline=deadline, is_retry=False,
                               is_restart=saved_checkpoint)
            if not await self.store.set_recovery(token, {**intent, "restarts": intent["restarts"] + 1}):
                raise WorkflowCommandStoreUnavailable("Restart lease was lost")
            channel, _ = routes._start_stream_execution(self.orchestrator, self.store, context, novel, prepared)
            channel.disconnect()
        except BaseException:
            self.orchestrator.finish(context, novel)
            if token in self.store.owners:
                await self.store.release(str(context.tenant_id), novel, command_id, token)
            raise
