"""仅在自主创作请求范围启用的物理请求计量契约。"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol


class RequestMeter(Protocol):
    async def reserve(self) -> str: ...
    async def finish(self, request_id: str, usage: dict[str, Any]) -> None: ...


active_model_meter: ContextVar[RequestMeter | None] = ContextVar("creative_model_meter", default=None)


@dataclass(frozen=True)
class CreativeRequestMeter:
    repository: Any
    tenant_id: str
    novel_id: str
    bucket: str
    stage: str

    async def reserve(self) -> str:
        return await self.repository.reserve(self.tenant_id, self.novel_id, self.bucket, self.stage)

    async def finish(self, request_id: str, usage: dict[str, Any]) -> None:
        await self.repository.finish_request(self.tenant_id, self.novel_id, request_id, usage)
