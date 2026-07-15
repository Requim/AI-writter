"""Public workflow event envelope used by the SSE API."""
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowEventType = Literal[
    "status",
    "reasoning",
    "content_delta",
    "quality",
    "interrupt",
    "progress",
    "completed",
    "heartbeat",
    "error",
]


class WorkflowEvent(BaseModel):
    id: int
    type: WorkflowEventType
    thread_id: str
    node: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_sse(self) -> str:
        return (
            f"id: {self.id}\n"
            f"event: {self.type}\n"
            f"data: {self.model_dump_json()}\n\n"
        )
