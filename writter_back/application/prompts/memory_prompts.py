"""分层记忆生成提示词（Plan A：S层故事状态 + L层章节摘要）"""


def build_chapter_summary_prompt(chapter_title: str, chapter_content: str) -> str:
    """生成 L 层章节摘要的提示词，将整章压缩为 ~150 字核心摘要"""
    return (
        f"请用150字以内概括以下章节的核心情节进展。\n"
        f"重点关注：主角关键行动、情节转折、埋下的伏笔。\n\n"
        f"章节标题：{chapter_title}\n"
        f"章节内容（开头2000字）：{chapter_content[:2000]}"
    )


def build_story_state_prompt(chapter_index: int, chapter_title: str, chapter_content: str) -> str:
    """生成 S 层故事状态的提示词，提取当前故事时间线/位置/冲突/人物关系"""
    return (
        f"根据最新章节内容，用300-500字更新当前故事状态。\n"
        f"需包含以下信息（对后续章节创作有用）：\n"
        f"1. 时间线进展（当前时间点、距离故事开始多久）\n"
        f"2. 主角当前位置和状态（地点、身体/心理状态）\n"
        f"3. 当前关键冲突/悬而未决的问题\n"
        f"4. 重要人物关系变化\n"
        f"5. 已揭示和未揭示的秘密\n\n"
        f"第{chapter_index + 1}章标题：{chapter_title}\n"
        f"章节内容：{chapter_content}"
    )


CHAPTER_SUMMARY_TEMPERATURE = 0.3
STORY_STATE_TEMPERATURE = 0.3
