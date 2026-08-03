"""LLM服务接口 - 服务层定义，基础设施层实现"""
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional


class LLMService(ABC):
    """LLM服务接口"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, 
                      temperature: float = 0.7, top_p: float = 1.0) -> str:
        """生成文本"""
        pass

    @abstractmethod
    def stream_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ) -> AsyncIterator[str]:
        """流式生成文本片段"""
        raise NotImplementedError
    
    @abstractmethod
    async def structured_generate(self, prompt: str, schema: Dict[str, Any], 
                                 system_prompt: Optional[str] = None,
                                 temperature: float = 0.3,
                                 top_p: float = 1.0,
                                 max_attempts: int | None = None) -> Dict[str, Any]:
        """结构化生成；max_attempts 可限制本次调用的总尝试次数。"""
        pass
    
    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7, top_p: float = 1.0) -> str:
        """对话生成"""
        pass
