"""小说仓储接口"""
from abc import ABC, abstractmethod
from typing import Optional, List
from ..entities.novel import Novel


class NovelRepository(ABC):
    """小说仓储接口"""
    
    @abstractmethod
    async def save(self, tenant_id: str, novel: Novel) -> Novel:
        """保存小说"""
        pass
    
    @abstractmethod
    async def find_by_id(self, tenant_id: str, novel_id: str) -> Optional[Novel]:
        """根据ID查找小说"""
        pass
    
    @abstractmethod
    async def find_all(self, tenant_id: str) -> List[Novel]:
        """查找租户的所有小说"""
        pass
    
    @abstractmethod
    async def delete(self, tenant_id: str, novel_id: str) -> None:
        """删除小说"""
        pass
    
    @abstractmethod
    async def update(self, tenant_id: str, novel: Novel) -> Novel:
        """更新小说"""
        pass
