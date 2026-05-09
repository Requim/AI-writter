"""章节实体"""
from dataclasses import dataclass, field
from uuid import UUID, uuid4
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class Chapter:
    """章节实体"""
    id: UUID = field(default_factory=uuid4)
    novel_id: Optional[UUID] = None
    chapter_index: int = 0
    title: Optional[str] = None
    
    outline: Optional[Dict[str, Any]] = None      # 章节细纲
    content: Optional[str] = None                  # 章节内容
    word_count: int = 0
    
    reflection_issues: List[Dict[str, Any]] = field(default_factory=list)
    user_decision: Optional[Dict[str, Any]] = None
    revision_count: int = 0
    revision_history: List[Dict[str, Any]] = field(default_factory=list)
    
    status: str = "draft"  # draft, writing, completed, revised
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def update_content(self, content: str) -> None:
        """更新章节内容"""
        self.content = content
        self.word_count = len(content)
        self.updated_at = datetime.now()
    
    def add_reflection_issue(self, issue: Dict[str, Any]) -> None:
        """添加反思问题"""
        self.reflection_issues.append(issue)
    
    def clear_reflection_issues(self) -> None:
        """清除反思问题（重新生成时）"""
        self.reflection_issues = []
    
    def is_valid_word_count(self) -> bool:
        """检查字数是否在3000-7000范围内"""
        return 3000 <= self.word_count <= 7000
