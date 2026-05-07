"""进度值对象"""
from dataclasses import dataclass


@dataclass
class Progress:
    """进度值对象 - 通过总纲进度条控制小说完结"""
    current_chapter: int = 0
    total_chapters: int = 0
    percentage: float = 0.0
    status: str = "draft"  # draft, writing, completed
    
    def update_progress(self, current: int, total: int) -> None:
        """更新进度"""
        self.current_chapter = current
        self.total_chapters = total
        self.percentage = (current / total * 100) if total > 0 else 0.0
        if current >= total and total > 0:
            self.status = "completed"
    
    def is_complete(self) -> bool:
        """是否已完成"""
        return self.status == "completed"
    
    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "current_chapter": self.current_chapter,
            "total_chapters": self.total_chapters,
            "percentage": round(self.percentage, 2),
            "status": self.status
        }
