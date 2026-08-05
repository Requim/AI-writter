"""大纲值对象（支持卷结构）"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Outline:
    """总纲领值对象"""
    story_background: str = ""                    # 故事背景设定
    main_characters: List[Dict[str, Any]] = field(default_factory=list)  # 主要人物
    main_plot: Dict[str, Any] = field(default_factory=dict)             # 主线剧情
    antagonist_plan: str = ""                    # 对手主动计划
    truth_reveal_ladder: List[Dict[str, Any]] = field(default_factory=list)  # 真相揭示阶梯
    cost_curve: List[Dict[str, Any]] = field(default_factory=list)      # 代价升级曲线
    relationship_turns: List[Dict[str, Any]] = field(default_factory=list)  # 关系转折
    chapters: List[Dict[str, Any]] = field(default_factory=list)        # 章节规划
    writing_style: str = ""                       # 写作风格指导
    total_chapters: int = 0                       # 总章节数
    volumes: List[Dict[str, Any]] = field(default_factory=list)  # 卷结构规划（可选）
    scale: Dict[str, Any] = field(default_factory=dict)  # 创建阶段规模契约镜像
    creative_brief: Dict[str, Any] = field(default_factory=dict)  # 全流程共用创作简报
    prompt_version: str = ""                    # 生成该总纲的提示词契约版本
    
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
