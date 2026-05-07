"""总纲领生成提示词"""


def build_outline_prompt(novel_type: str, title: str, summary: str) -> str:
    """生成总纲领的提示词"""
    return f"""
请为以下小说生成完整的总纲领：
类型：{novel_type}
书名：{title}
简介：{summary}

总纲领应包含：
1. story_background: 故事背景设定（1200-1800字）
2. main_characters: 主要人物列表（至少9个，每个包含：姓名、性格、目标、冲突）
3. main_plot: 主线剧情（包含：开端、发展、高潮、结局）
4. chapters: 章节规划（建议120-300章，每章包含：theme主题、key_events关键事件）
5. writing_style: 写作风格指导（200-400字）
6. total_chapters: 总章节数（整数）

输出JSON格式，确保格式正确可解析。
"""


OUTLINE_SCHEMA = {
    "story_background": "string",
    "main_characters": "array",
    "main_plot": "object",
    "chapters": "array",
    "writing_style": "string",
    "total_chapters": "integer",
}
