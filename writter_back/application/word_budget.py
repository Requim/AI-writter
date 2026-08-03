"""章节与场景共享的确定性字数预算。"""

DEFAULT_TARGET_WORDS = 5000


def chapter_target_words(outline: dict) -> int:
    """优先使用细纲目标，并限制到产品允许的章节范围。"""
    value = outline.get("estimated_word_count", DEFAULT_TARGET_WORDS)
    try:
        target = int(value)
    except (TypeError, ValueError):
        target = DEFAULT_TARGET_WORDS
    return max(3000, min(7000, target))
