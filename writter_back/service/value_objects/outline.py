"""大纲值对象（支持卷结构）"""
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
    volumes: List[Dict[str, Any]] = field(default_factory=list)  # 卷结构规划（可选）
    
    def get_chapter_plan(self, index: int) -> Optional[Dict[str, Any]]:
        """获取指定章节的规划"""
        if 0 <= index < len(self.chapters):
            return self.chapters[index]
        return None
    
    def get_volume_for_chapter(self, chapter_index: int) -> Optional[Dict[str, Any]]:
        """获取指定章节所属的卷"""
        one_based = chapter_index + 1
        for vol in self.volumes:
            start = vol.get("start_chapter", 0)
            end = vol.get("end_chapter", 0)
            if start <= one_based <= end:
                return vol
        return None
