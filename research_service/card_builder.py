"""在没有外部模型时生成低置信度的元数据研究卡片。"""

from __future__ import annotations

from .contracts import ChapterIndex, NovelMetadata, NovelPatternCard, OpeningMetrics


def _opening_candidate(metadata: NovelMetadata, index: ChapterIndex) -> str:
    text = " ".join((metadata.title, metadata.summary, *index.titles[:6]))
    for marker, value in (
        (("系统", "任务", "签到"), "system_or_mission"),
        (("重生", "穿越"), "rebirth_or_transport"),
        (("退婚", "婚约", "关系"), "relationship_collision"),
        (("谜", "秘密", "真相"), "mystery_question"),
        (("危", "追杀", "死亡"), "immediate_crisis"),
    ):
        if any(item in text for item in marker):
            return value
    return "ordinary_to_inciting_event"


def build_metadata_card(metadata: NovelMetadata, index: ChapterIndex) -> NovelPatternCard:
    """只使用详情和目录生成候选，不把启发式当成最终规律。"""
    sanitized_metadata = metadata.model_copy(update={"summary": ""})
    return NovelPatternCard(
        metadata=sanitized_metadata,
        chapter_index=index,
        highlight_mechanisms=(),
        opening_pattern=_opening_candidate(metadata, index),
        opening_beats=index.titles[:6],
        reader_promise="",
        plot_engine="待授权首章分析或外部总结模型确认",
        originality_directions=("重新设计人物目标、冲突条件和世界规则，不复用来源作品组合。",),
        confidence="low",
        limitations=("当前只使用元数据和目录标题，开局标签属于候选判断。",),
    )


def attach_opening_metrics(card: NovelPatternCard, metrics: OpeningMetrics) -> NovelPatternCard:
    return card.model_copy(update={"opening_metrics": metrics})
