"""长期记忆接口"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class MemoryService(ABC):
    """长期记忆接口"""
    
    @abstractmethod
    async def store(self, tenant_id: str, novel_id: str, content: str, metadata: Dict[str, Any]) -> str:
        """存储记忆"""
        pass
    
    @abstractmethod
    async def retrieve(self, tenant_id: str, novel_id: str, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """检索相关记忆"""
        pass
    
    @abstractmethod
    async def get_novel_context(self, tenant_id: str, novel_id: str) -> str:
        """获取小说完整上下文"""
        pass

    @abstractmethod
    async def get_hierarchical_context(self, tenant_id: str, novel_id: str, current_index: int, m_count: int = 3) -> str:
        """获取分层上下文：S层故事状态 + M层近期章节 + L层历史章节摘录"""
        pass

    @abstractmethod
    async def store_chapter_memory(self, tenant_id: str, novel_id: str, chapter: Dict[str, Any]) -> str:
        """存储章节到长期记忆"""
        pass

    @abstractmethod
    async def delete_chapter_memory(self, tenant_id: str, novel_id: str, chapter_index: int) -> None:
        """删除指定章节索引的旧记忆，确保每章只有一条记忆"""
        pass

    @abstractmethod
    async def store_chapter_summary(self, tenant_id: str, novel_id: str, chapter_index: int, summary_content: str) -> str:
        """Store L-layer chapter summary"""
        pass

    @abstractmethod
    async def update_story_state(self, tenant_id: str, novel_id: str, state_content: str) -> None:
        """更新S层故事状态"""
        pass
