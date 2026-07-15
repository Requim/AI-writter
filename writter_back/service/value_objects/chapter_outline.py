"""章节细纲值对象"""
from dataclasses import dataclass, field
from typing import List, Dict, Any


@dataclass
class ChapterOutline:
    """章节细纲值对象"""
    chapter_number: int = 0
    title: str = ""
    scenes: List[Dict[str, Any]] = field(default_factory=list)
    key_plot_points: List[str] = field(default_factory=list)
    estimated_word_count: int = 4500
    character_developments: List[str] = field(default_factory=list)
    foreshadowing: List[str] = field(default_factory=list)
    
    def is_valid_word_estimate(self) -> bool:
        """检查预估字数是否合理"""
        return 3000 <= self.estimated_word_count <= 7000
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "title": self.title,
            "scenes": self.scenes,
            "key_plot_points": self.key_plot_points,
            "estimated_word_count": self.estimated_word_count,
            "character_developments": self.character_developments,
            "foreshadowing": self.foreshadowing
        }
