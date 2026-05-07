"""小说聚合根"""
from dataclasses import dataclass, field
from uuid import UUID, uuid4
from datetime import datetime
from typing import List, Optional

from .chapter import Chapter
from ..value_objects.novel_type import NovelType
from ..value_objects.outline import Outline
from ..value_objects.progress import Progress


@dataclass
class Novel:
    """小说聚合根 - 整个系统的核心实体"""
    id: UUID = field(default_factory=uuid4)
    user_id: Optional[UUID] = None
    novel_type: str = ""                     # 小说类型（必选）
    title: Optional[str] = None               # 书名
    summary: Optional[str] = None             # 简介
    total_outline: Optional[Outline] = None   # 总纲领
    thread_id: Optional[str] = None           # LangGraph 工作流线程ID
    
    chapters: List[Chapter] = field(default_factory=list)
    progress: Progress = field(default_factory=Progress)
    
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def add_chapter(self, chapter: 'Chapter') -> None:
        """添加章节"""
        self.chapters.append(chapter)
        self.progress.update_progress(
            len(self.chapters),
            self.total_outline.total_chapters if self.total_outline else 0
        )
        self.updated_at = datetime.now()
    
    def is_completed(self) -> bool:
        """判断是否完结"""
        return self.progress.is_complete()
    
    def get_chapter(self, index: int) -> Optional['Chapter']:
        """根据索引获取章节"""
        if 0 <= index < len(self.chapters):
            return self.chapters[index]
        return None
