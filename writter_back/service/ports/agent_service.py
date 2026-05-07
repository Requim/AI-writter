"""Agent执行接口"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class AgentOrchestrator(ABC):
    """Agent执行接口"""
    
    @abstractmethod
    async def invoke(self, thread_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """调用Agent"""
        pass
    
    @abstractmethod
    async def resume(self, thread_id: str, resume_value: Any) -> Dict[str, Any]:
        """恢复中断的Agent"""
        pass
    
    @abstractmethod
    async def stream(self, thread_id: str, input_data: Dict[str, Any]):
        """流式调用Agent"""
        pass

    async def aclose(self):
        """释放资源（可选实现）"""
        pass
