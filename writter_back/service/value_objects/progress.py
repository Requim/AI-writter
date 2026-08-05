"""进度值对象"""

from dataclasses import dataclass
from typing import Any


@dataclass
class Progress:
    """进度值对象 - 通过总纲进度条控制小说完结"""

    current_chapter: int = 0
    total_chapters: int = 0
    percentage: float = 0.0
    status: str = "draft"  # draft, writing, completed
    completed_words: int = 0
    target_words: int = 0
    word_percentage: float = 0.0
    current_volume: int = 0
    total_volumes: int = 0
    volume_percentage: float = 0.0
    plan_version: int = 0
    plan_status: str = "missing"
    drift_severity: str = "none"
    checkpoint_sync: dict[str, Any] | None = None

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
        payload = {
            "current_chapter": self.current_chapter,
            "total_chapters": self.total_chapters,
            "percentage": round(self.percentage, 2),
            "status": self.status,
            "completed_words": self.completed_words,
            "target_words": self.target_words,
            "word_percentage": round(self.word_percentage, 2),
            "current_volume": self.current_volume,
            "total_volumes": self.total_volumes,
            "volume_percentage": round(self.volume_percentage, 2),
            "plan_version": self.plan_version,
            "plan_status": self.plan_status,
            "drift_severity": self.drift_severity,
        }
        if self.checkpoint_sync is not None:
            payload["checkpoint_sync"] = self.checkpoint_sync
        return payload
