"""书名生成提示词"""


def build_title_prompt(novel_type: str) -> str:
    """生成书名的提示词"""
    return f"请为类型为「{novel_type}」的小说生成5个优质书名，每行一个，要求题目内涵贯穿全文、吸引人且符合类型特点。"


TITLE_TEMPERATURE = 0.9
