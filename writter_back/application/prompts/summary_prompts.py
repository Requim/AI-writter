"""简介生成提示词"""


def build_summary_prompt(novel_type: str, title: str) -> str:
    """生成简介的提示词"""
    return (
        f"请为以下小说生成一段200-300字的简介：\n"
        f"类型：{novel_type}\n"
        f"书名：{title}\n\n"
        f"要求：吸引人，突出故事核心冲突和看点。"
    )


SUMMARY_TEMPERATURE = 0.8
