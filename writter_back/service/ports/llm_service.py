"""LLM服务接口 - 服务层定义，基础设施层实现"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class LLMService(ABC):
    """LLM服务接口"""
    
    @abstractmethod
    async def generate(self, prompt: str, system_prompt: Optional[str] = None, 
                      temperature: float = 0.7) -> str:
        """生成文本"""
        pass
    
    @abstractmethod
    async def structured_generate(self, prompt: str, schema: Dict[str, Any], 
                                 system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """结构化生成（用于生成细纲等）"""
        pass
    
    @abstractmethod
    async def chat(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> str:
        """对话生成"""
        pass
