import pytest

from application.agents.chapter_compaction_node import (
    chapter_compaction_node,
    chapter_target_words,
    compaction_reasons,
    repeated_sentences,
)
from application.scene_queue import distribute_scene_targets


class _CompactionLLM:
    def __init__(self, result: str) -> None:
        self.result = result
        self.calls = 0

    async def generate(self, prompt: str, **kwargs) -> str:
        self.calls += 1
        return self.result


def _state(content: str, target: int = 3000) -> dict:
    return {
        "current_chapter_content": content,
        "current_chapter_index": 0,
        "chapter_outlines": [{"estimated_word_count": target}],
        "scene_ledger": [],
    }


def test_compaction_triggers_are_deterministic() -> None:
    repeated = "这是一句长度超过二十个字符而且会被完整重复的测试句子。"
    content = f"{repeated}\n{repeated}"

    assert repeated_sentences(content) == [repeated]
    assert "完全重复长句" in compaction_reasons(_state(content, 7000))[0]
    assert chapter_target_words({"estimated_word_count": "9000"}) == 7000


def test_scene_targets_follow_chapter_budget() -> None:
    targets = distribute_scene_targets(3, 4200)

    assert sum(targets) == 4200
    assert len(targets) == 3


@pytest.mark.asyncio
async def test_compaction_runs_once_and_preserves_anchor() -> None:
    anchor = "她关掉终端，倒计时仍停在三十六小时。"
    original = "正文推进。" * 800 + "\n\n" + anchor
    compacted = "正文推进。" * 570 + "\n\n" + anchor
    llm = _CompactionLLM(compacted)

    command = await chapter_compaction_node(
        _state(original),
        {"configurable": {"adaptive_compaction_enabled": True, "llm_config": {"llm_instance": llm}}},
    )

    assert llm.calls == 1
    assert command.update["current_chapter_content"] == compacted
    assert command.update["compaction_metrics"]["applied"] is True


@pytest.mark.asyncio
async def test_invalid_compaction_keeps_original() -> None:
    anchor = "原有结尾必须保留。"
    original = "正文推进。" * 800 + anchor
    llm = _CompactionLLM("过短且没有原有结尾")

    command = await chapter_compaction_node(
        _state(original),
        {"configurable": {"adaptive_compaction_enabled": True, "llm_config": {"llm_instance": llm}}},
    )

    assert command.update["current_chapter_content"] == original
    assert command.update["compaction_metrics"]["applied"] is False


@pytest.mark.asyncio
async def test_compaction_rejects_anchor_followed_by_a_new_ending() -> None:
    anchor = "她关掉终端，倒计时仍停在三十六小时。"
    original = "正文推进。" * 800 + "\n\n" + anchor
    changed_ending = "正文推进。" * 570 + "\n\n" + anchor + "\n\n屏幕随后重新亮起。"
    llm = _CompactionLLM(changed_ending)

    command = await chapter_compaction_node(
        _state(original),
        {"configurable": {"adaptive_compaction_enabled": True, "llm_config": {"llm_instance": llm}}},
    )

    assert llm.calls == 1
    assert command.update["current_chapter_content"] == original
    assert command.update["compaction_metrics"]["applied"] is False
