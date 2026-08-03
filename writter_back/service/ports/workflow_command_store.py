"""工作流命令幂等存储端口。"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class WorkflowCommandClaimStatus(StrEnum):
    """命令领取结果。"""

    ACQUIRED = "acquired"
    IN_PROGRESS = "in_progress"
    ALREADY_APPLIED = "already_applied"


@dataclass(frozen=True)
class WorkflowCommandClaim:
    """命令租约；只有成功领取时才包含租约令牌。"""

    status: WorkflowCommandClaimStatus
    lease_token: str | None = None


class WorkflowCommandStoreUnavailable(RuntimeError):
    """幂等存储当前不可用。"""


class WorkflowCommandStore(ABC):
    """隔离业务层与具体幂等存储实现。"""

    @abstractmethod
    async def claim(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        ttl_seconds: float,
    ) -> WorkflowCommandClaim:
        """原子领取命令，返回当前命令状态。"""

    @abstractmethod
    async def finalize(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        lease_token: str,
        ttl_seconds: float,
    ) -> bool:
        """仅由租约持有者原子写入已执行终态。"""

    @abstractmethod
    async def release(
        self,
        tenant_id: str,
        novel_id: str,
        command_id: str,
        lease_token: str,
    ) -> bool:
        """仅由租约持有者原子释放未执行命令。"""

    @abstractmethod
    async def ping(self) -> None:
        """检查幂等存储是否可用。"""

    @abstractmethod
    async def aclose(self) -> None:
        """释放存储连接。"""
