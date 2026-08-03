"""Optional, bounded compaction between chapter drafting and review."""

import logging
import re
from collections import Counter
from typing import Literal

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from application.prompts.compaction_prompts import build_compaction_prompt
from application.schemas.agent_state import NovelAgentState
from application.streaming import emit_workflow_event
from application.word_budget import chapter_target_words

logger = logging.getLogger("uvicorn")


def repeated_sentences(content: str) -> list[str]:
    """Find exact repeated long sentences without fuzzy NLP heuristics."""
    parts = re.split(r"(?<=[。！？!?])\s*", content)
    normalized = [re.sub(r"\s+", "", part) for part in parts]
    counts = Counter(part for part in normalized if len(part) >= 20)
    return [sentence for sentence, count in counts.items() if count >= 2]


def compaction_reasons(state: NovelAgentState) -> list[str]:
    """Return deterministic reasons for an optional compaction pass."""
    content = str(state.get("current_chapter_content") or "")
    outline = _current_outline(state)
    target = chapter_target_words(outline)
    reasons = []
    if len(content) > target * 1.15:
        reasons.append(f"章节长度 {len(content)} 超过目标 {target} 的 115%")
    ledger = state.get("scene_ledger") or []
    if any(_scene_over_budget(item) for item in ledger if isinstance(item, dict)):
        reasons.append("至少一个场景超过自身目标的 125%")
    repeats = repeated_sentences(content)
    if repeats:
        reasons.append(f"存在 {len(repeats)} 处完全重复长句")
    return reasons


def _current_outline(state: NovelAgentState) -> dict:
    outlines = state.get("chapter_outlines") or []
    return outlines[-1] if outlines and isinstance(outlines[-1], dict) else {}


def _scene_over_budget(item: dict) -> bool:
    actual = item.get("actual_character_count")
    target = item.get("target_character_count")
    return isinstance(actual, int) and isinstance(target, int) and actual > target * 1.25


def _ending_anchor(content: str) -> str:
    paragraphs = [part.strip() for part in content.splitlines() if part.strip()]
    tail = paragraphs[-1] if paragraphs else content.strip()
    return tail[-120:]


def _valid_compaction(original: str, compacted: str, ending_anchor: str) -> bool:
    if not compacted or len(compacted) > len(original):
        return False
    if len(compacted) < len(original) * 0.7:
        return False
    normalized = "".join(compacted.split())
    normalized_anchor = "".join(ending_anchor.split())
    return bool(normalized_anchor and normalized.endswith(normalized_anchor))


def _result(content: str, reasons: list[str], applied: bool) -> Command:
    metrics = {"checked": True, "applied": applied, "reasons": reasons}
    return Command(
        goto="router_agent",
        update={"current_chapter_content": content, "compaction_checked": True, "compaction_metrics": metrics},
    )


async def chapter_compaction_node(
    state: NovelAgentState, config: RunnableConfig
) -> Command[Literal["router_agent"]]:
    """Compact a draft once when deterministic budget checks trigger."""
    content = str(state.get("current_chapter_content") or "")
    reasons = compaction_reasons(state)
    enabled = config["configurable"].get("adaptive_compaction_enabled", False)
    if not enabled or not reasons or not content:
        return _result(content, reasons, False)
    llm = config["configurable"].get("llm_config", {}).get("llm_instance")
    if not llm:
        return _result(content, reasons, False)
    outline = _current_outline(state)
    anchor = _ending_anchor(content)
    emit_workflow_event("status", {"status": "started", "message": "正在压缩重复与冗余表达"}, "chapter_compaction_node")
    try:
        prompt = build_compaction_prompt(content, outline, chapter_target_words(outline), reasons, anchor)
        compacted = (await llm.generate(prompt, temperature=0.2)).strip()
    except Exception as exc:
        logger.warning("【章节压缩节点】压缩失败，保留原稿 | %s", exc)
        return _result(content, reasons, False)
    if not _valid_compaction(content, compacted, anchor):
        logger.warning("【章节压缩节点】结果未通过保真校验，保留原稿")
        return _result(content, reasons, False)
    index = state.get("current_chapter_index", 0)
    emit_workflow_event("content_delta", {"chapter_index": index, "operation": "reset", "text": compacted}, "chapter_compaction_node")
    logger.info("【章节压缩节点】完成 | %s -> %s", len(content), len(compacted))
    return _result(compacted, reasons, True)
