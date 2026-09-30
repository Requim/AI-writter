"""结构化总结适配器；外部模型只返回研究字段，不保存正文。"""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from .card_builder import build_metadata_card
from .contracts import ChapterIndex, NovelMetadata, NovelPatternCard, OpeningMetrics


class ResearchSummarizer(Protocol):
    async def summarize(
        self,
        metadata: NovelMetadata,
        chapter_index: ChapterIndex,
        opening_text: str = "",
        opening_metrics: OpeningMetrics | None = None,
    ) -> NovelPatternCard: ...


class RuleBasedSummarizer:
    async def summarize(
        self,
        metadata: NovelMetadata,
        chapter_index: ChapterIndex,
        opening_text: str = "",
        opening_metrics: OpeningMetrics | None = None,
    ) -> NovelPatternCard:
        card = build_metadata_card(metadata, chapter_index)
        if opening_metrics:
            card = card.model_copy(update={"opening_metrics": opening_metrics})
        return card


class FallbackSummarizer:
    def __init__(
        self,
        primary: ResearchSummarizer,
        fallback: ResearchSummarizer | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or RuleBasedSummarizer()

    async def summarize(
        self,
        metadata: NovelMetadata,
        chapter_index: ChapterIndex,
        opening_text: str = "",
        opening_metrics: OpeningMetrics | None = None,
    ) -> NovelPatternCard:
        """外部模型或结构化解析失败时保留低置信度研究结果。"""
        try:
            return await self.primary.summarize(
                metadata, chapter_index, opening_text, opening_metrics
            )
        except (httpx.HTTPError, IndexError, KeyError, TypeError, ValueError):
            return await self.fallback.summarize(
                metadata, chapter_index, opening_text, opening_metrics
            )


class OpenAICompatibleSummarizer:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def summarize(
        self,
        metadata: NovelMetadata,
        chapter_index: ChapterIndex,
        opening_text: str = "",
        opening_metrics: OpeningMetrics | None = None,
    ) -> NovelPatternCard:
        prompt = self._prompt(metadata, chapter_index, opening_text, opening_metrics)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "temperature": 0.1,
                    "messages": [
                        {"role": "system", "content": "只输出符合要求的 JSON，不复述原文。"},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        payload = self._json_payload(content)
        sanitized = metadata.model_copy(update={"summary": ""})
        return NovelPatternCard(
            metadata=sanitized,
            chapter_index=chapter_index,
            opening_metrics=opening_metrics,
            **payload,
        )

    @staticmethod
    def _json_payload(content: str) -> dict:
        text = str(content).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("模型总结不是 JSON 对象")
        return data

    @staticmethod
    def _prompt(
        metadata: NovelMetadata,
        chapter_index: ChapterIndex,
        opening_text: str,
        opening_metrics: OpeningMetrics | None,
    ) -> str:
        source = {
            "title": metadata.title, "author": metadata.author,
            "category": metadata.source_category, "summary": metadata.summary,
            "chapter_titles": chapter_index.titles, "chapter_count": chapter_index.total_count,
            "opening_metrics": opening_metrics.model_dump() if opening_metrics else None,
            "opening_text": opening_text[:20000] if opening_text else "",
        }
        return (
            "将下面资料总结为原创创作研究卡片。不要输出原句、对白、人物专名、独特设定组合或连续剧情。"
            "只输出 JSON，字段为 highlight_mechanisms(list[str]), opening_pattern(str), "
            "opening_beats(list[str]), reader_promise(str), plot_engine(str), "
            "originality_directions(list[str]), confidence(high|medium|low), limitations(list[str])。"
            f"资料：{json.dumps(source, ensure_ascii=False)}"
        )


def create_summarizer(base_url: str, api_key: str, model: str) -> ResearchSummarizer:
    if base_url and api_key and model:
        return FallbackSummarizer(OpenAICompatibleSummarizer(base_url, api_key, model))
    return RuleBasedSummarizer()
