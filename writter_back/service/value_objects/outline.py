"""大纲值对象"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Outline:
    """总纲领值对象"""
    story_background: str = ""                    # 故事背景设定
    main_characters: List[Dict[str, Any]] = field(default_factory=list)  # 主要人物
    main_plot: Dict[str, Any] = field(default_factory=dict)             # 主线剧情
    chapters: List[Dict[str, Any]] = field(default_factory=list)        # 章节规划
    writing_style: str = ""                       # 写作风格指导
    total_chapters: int = 0                       # 总章节数
    
    def get_chapter_plan(self, index: int) -> Optional[Dict[str, Any]]:
        """获取指定章节的规划"""
        if 0 <= index < len(self.chapters):
            return self.chapters[index]
        return None
