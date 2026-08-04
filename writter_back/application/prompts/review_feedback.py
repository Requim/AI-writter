"""将人工审核意见注入下一版生成提示词。"""

from typing import Any


def append_review_feedback(prompt: str, feedback: Any) -> str:
    """仅在存在有效文本时追加本轮人工修改要求。"""
    text = str(feedback or "").strip()
    if not text:
        return prompt
    return f"{prompt}\n\n【本轮人工修改要求】\n{text}"
