import httpx
import pytest

from research_service.contracts import ChapterIndex, NovelMetadata
from research_service.summarizer import FallbackSummarizer


class FailingSummarizer:
    async def summarize(self, *_args, **_kwargs):
        request = httpx.Request("POST", "https://api.example.com/chat/completions")
        response = httpx.Response(400, request=request)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)


@pytest.mark.asyncio
async def test_model_failure_falls_back_to_metadata_card() -> None:
    summarizer = FallbackSummarizer(FailingSummarizer())
    metadata = NovelMetadata(
        source_url="https://www.biquge.pro/novel/1.html",
        source_id="1",
        title="测试小说",
        source_category="玄幻",
        summary="系统任务开启",
    )
    index = ChapterIndex(titles=("第一章 任务",), total_count=1, digest="a" * 64)
    card = await summarizer.summarize(metadata, index)
    assert card.confidence == "low"
    assert card.opening_pattern == "system_or_mission"
