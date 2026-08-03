"""Prompts for bounded, optional chapter compaction."""

import json

from application.continuity import compact_text
from application.prompts.version import PROMPT_VERSION


def build_compaction_prompt(
    content: str,
    chapter_outline: dict,
    target_words: int,
    reasons: list[str],
    ending_anchor: str,
) -> str:
    """Build a loss-averse compaction request for an overlong draft."""
    contract = json.dumps(chapter_outline, ensure_ascii=False, indent=2)
    reason_text = "\n".join(f"- {reason}" for reason in reasons)
    return f"""[PROMPT_VERSION:{PROMPT_VERSION}]
你是一名小说责任编辑。请压缩下面的章节正文，而不是重写剧情。

【触发原因】
{reason_text}

【硬性要求】
1. 目标长度约 {target_words} 字，只删除重复解释、重复情绪和不推动场景的描写。
2. 保留人物行动、反制、信息增量、不可逆代价、因果链和 POV 知识边界。
3. 不新增人物、设定、事件、线索或结论，不改变章节事实顺序。
4. 以下结尾锚点必须原样保留在输出结尾附近：{ending_anchor}
5. 直接输出压缩后的完整正文，不要解释、标题、Markdown 标记或编辑批注。

【章节契约】
{compact_text(contract, 5000)}

【待压缩正文】
{content}
"""
