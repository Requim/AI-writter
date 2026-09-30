"""后台采集批次执行器；失败样本只记录错误，不伪造结果。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from .biquge import BiqugeCatalogAdapter
from .contracts import BatchRequest, ResearchSample
from .repository import ResearchRepository
from .sampling import SampleQuota
from .service import ResearchKnowledgeService
from .summarizer import ResearchSummarizer, create_summarizer
from .taxonomy import assign_project_genres


class ResearchBatchRunner:
    def __init__(
        self,
        repository: ResearchRepository,
        knowledge: ResearchKnowledgeService,
        allow_opening: bool = False,
        summarizer: ResearchSummarizer | None = None,
    ) -> None:
        self.repository = repository
        self.knowledge = knowledge
        self.allow_opening = allow_opening
        self.summarizer = summarizer or create_summarizer("", "", "")

    async def run(self, request: BatchRequest, job_id: str) -> None:
        total = request.sample_target_per_category * len(request.categories)
        await self.repository.update_job(job_id, status="running", phase="discovering", total=total)
        processed = 0
        failures = []
        async with BiqugeCatalogAdapter() as adapter:
            for category in request.categories:
                try:
                    processed, category_failures = await self._run_category(
                        adapter, request, category, processed, job_id
                    )
                    failures.extend(category_failures)
                except Exception as exc:
                    failures.append(f"{category}: {type(exc).__name__}: {exc}")
        status = "completed" if processed == total and not failures else "partial" if processed else "failed"
        await self.repository.update_job(
            job_id, status=status, phase=status, processed=processed,
            error="; ".join(failures)[:1000] if failures else None,
        )

    async def _run_category(self, adapter, request, category, processed, job_id):
        target = request.sample_target_per_category
        quota = SampleQuota.from_total(target + max(5, target))
        candidates = await adapter.fetch_strata(
            category, request.sources.get(category, {}), quota=quota,
            allow_shortage=True, include_remaining=True,
        )
        initial_processed = processed
        failures = []
        await self.repository.update_job(job_id, phase=f"collecting:{category}")
        for candidate in candidates:
            if processed - initial_processed >= target:
                return processed, []
            try:
                inserted = await self._collect_candidate(adapter, request, category, candidate)
                if not inserted:
                    failures.append(f"{candidate.url}: 重复样本")
                    continue
                processed += 1
                await self.repository.update_job(job_id, processed=processed)
            except Exception as exc:
                failures.append(f"{candidate.url}: {type(exc).__name__}: {exc}")
        collected = processed - initial_processed
        if collected >= target:
            return processed, []
        details = "; ".join(failures[:5])
        return processed, [f"{category}: 仅新增 {collected}/{target} 个样本; {details}"]

    async def _collect_candidate(self, adapter, request, category, candidate) -> bool:
        metadata, index = await adapter.fetch_detail(candidate.url, category)
        opening_text = ""
        opening_metrics = None
        if request.authorized_opening and self.allow_opening and metadata.first_chapter_url:
            opening = await adapter.fetch_opening(metadata.first_chapter_url, authorized=True)
            try:
                opening_text, opening_metrics = opening.text, opening.metrics
            finally:
                opening.discard()
        card = await self.summarizer.summarize(
            metadata, index, opening_text=opening_text, opening_metrics=opening_metrics
        )
        primary, secondary = assign_project_genres(
            metadata.source_category, metadata.project_genres
        )
        sample = self._sample(request.batch_id, primary, secondary, card)
        return await self.knowledge.ingest_sample(sample) is not None

    @staticmethod
    def _sample(batch_id, primary, secondary, card) -> ResearchSample:
        payload = card.model_dump(mode="json")
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return ResearchSample(
            sample_id=f"sample-{uuid4().hex}",
            batch_id=batch_id,
            sample_digest=digest,
            primary_project_genre=primary,
            secondary_project_genres=secondary,
            card=card,
            observed_at=datetime.now(timezone.utc),
        )
