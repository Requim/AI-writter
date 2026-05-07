"""长期记忆接口"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class MemoryService(ABC):
    """长期记忆接口"""
    
    @abstractmethod
    async def store(self, novel_id: str, content: str, metadata: Dict[str, Any]) -> str:
        """存储记忆"""
        pass
    
    @abstractmethod
    async def retrieve(self, novel_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索相关记忆"""
        pass
    
    @abstractmethod
    async def get_novel_context(self, novel_id: str) -> str:
        """获取小说完整上下文"""
        pass
    
    @abstractmethod
    async def store_chapter_memory(self, novel_id: str, chapter: Dict[str, Any]) -> str:
        """存储章节到长期记忆"""
        pass
