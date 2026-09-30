"""研究服务仓储；默认按类型知识包检索。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB

from .contracts import BatchRequest, GenreKnowledgePackage, ResearchSample
from .models import (
    GenreKnowledgeVersionModel,
    GenreTermModel,
    ResearchBatchModel,
    ResearchJobModel,
    ResearchSampleModel,
)
from .taxonomy import normalize_term


class ResearchRepository(Protocol):
    async def add_batch(self, batch_id: str, request: dict) -> None: ...
    async def add_job(self, job_id: str, batch_id: str) -> None: ...
    async def claim_next_job(self) -> tuple[str, BatchRequest] | None: ...
    async def get_job(self, job_id: str) -> dict | None: ...
    async def update_job(self, job_id: str, **values: object) -> None: ...
    async def add_sample(self, sample: ResearchSample) -> bool: ...
    async def list_samples(self, project_genre: str) -> list[ResearchSample]: ...
    async def next_version(self, project_genre: str) -> int: ...
    async def add_package(self, package: GenreKnowledgePackage) -> None: ...
    async def list_packages(self, project_genre: str, approved_only: bool = True) -> list[GenreKnowledgePackage]: ...
    async def review_package(self, version_id: str, decision: str) -> GenreKnowledgePackage | None: ...


class InMemoryResearchRepository:
    """测试和本地演示使用的无外部依赖仓储。"""

    def __init__(self) -> None:
        self.batches: dict[str, dict] = {}
        self.jobs: dict[str, dict] = {}
        self.samples: dict[tuple[str, str, str], ResearchSample] = {}
        self.packages: dict[str, GenreKnowledgePackage] = {}

    async def add_batch(self, batch_id: str, request: dict) -> None:
        self.batches[batch_id] = {"batch_id": batch_id, "request": request, "status": "queued"}

    async def add_job(self, job_id: str, batch_id: str) -> None:
        self.jobs[job_id] = {
            "job_id": job_id, "batch_id": batch_id, "status": "queued",
            "phase": "queued", "processed": 0, "total": 0, "error": None,
        }

    async def claim_next_job(self) -> tuple[str, BatchRequest] | None:
        for job_id, job in self.jobs.items():
            if job["status"] != "queued":
                continue
            job["status"] = "running"
            return job_id, BatchRequest.model_validate(self.batches[job["batch_id"]]["request"])
        return None

    async def get_job(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    async def update_job(self, job_id: str, **values: object) -> None:
        if job_id not in self.jobs:
            return
        self.jobs[job_id].update(values)

    async def add_sample(self, sample: ResearchSample) -> bool:
        key = ("biquge.pro", sample.card.metadata.source_id, sample.sample_digest)
        if key in self.samples:
            return False
        self.samples[key] = sample
        return True

    async def list_samples(self, project_genre: str) -> list[ResearchSample]:
        return [item for item in self.samples.values()
                if item.primary_project_genre == project_genre
                or project_genre in item.secondary_project_genres]

    async def next_version(self, project_genre: str) -> int:
        versions = [item.version for item in self.packages.values() if item.project_genre == project_genre]
        return max(versions, default=0) + 1

    async def add_package(self, package: GenreKnowledgePackage) -> None:
        self.packages[package.knowledge_version_id] = package

    async def list_packages(self, project_genre: str, approved_only: bool = True) -> list[GenreKnowledgePackage]:
        items = [item for item in self.packages.values() if item.project_genre == project_genre]
        if approved_only:
            items = [item for item in items if item.status == "approved"]
            return sorted(items, key=lambda item: item.version, reverse=True)[:1]
        return sorted(items, key=lambda item: item.version, reverse=True)

    async def review_package(self, version_id: str, decision: str) -> GenreKnowledgePackage | None:
        package = self.packages.get(version_id)
        if package is None:
            return None
        status = "approved" if decision == "approve" else "rejected"
        updated = package.model_copy(update={"status": status})
        self.packages[version_id] = updated
        return updated


class SqlAlchemyResearchRepository:
    """生产仓储；所有表只属于研究服务自己的数据库。"""

    def __init__(self, session_factory) -> None:
        self.sessions = session_factory

    async def add_batch(self, batch_id: str, request: dict) -> None:
        async with self.sessions() as session, session.begin():
            session.add(ResearchBatchModel(batch_id=batch_id, request_json=request))

    async def add_job(self, job_id: str, batch_id: str) -> None:
        async with self.sessions() as session, session.begin():
            session.add(ResearchJobModel(job_id=job_id, batch_id=batch_id))

    async def claim_next_job(self) -> tuple[str, BatchRequest] | None:
        from sqlalchemy import select
        async with self.sessions() as session, session.begin():
            job = await session.scalar(
                select(ResearchJobModel)
                .where(ResearchJobModel.status == "queued")
                .order_by(ResearchJobModel.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            batch = await session.get(ResearchBatchModel, job.batch_id)
            if batch is None:
                job.status, job.error = "failed", "批次记录不存在"
                return None
            job.status = "running"
            return job.job_id, BatchRequest.model_validate(batch.request_json)

    async def get_job(self, job_id: str) -> dict | None:
        async with self.sessions() as session:
            row = await session.get(ResearchJobModel, job_id)
            if row is None:
                return None
            return {
                "job_id": row.job_id, "batch_id": row.batch_id, "status": row.status,
                "phase": row.phase, "processed": row.processed, "total": row.total,
                "error": row.error,
            }

    async def update_job(self, job_id: str, **values: object) -> None:
        async with self.sessions() as session, session.begin():
            row = await session.get(ResearchJobModel, job_id)
            if row is None:
                return
            for key, value in values.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(timezone.utc)

    async def add_sample(self, sample: ResearchSample) -> bool:
        async with self.sessions() as session, session.begin():
            exists = await session.scalar(
                select(ResearchSampleModel.sample_id).where(
                    ResearchSampleModel.source_id == sample.card.metadata.source_id,
                    ResearchSampleModel.sample_digest == sample.sample_digest,
                )
            )
            if exists:
                return False
            session.add(ResearchSampleModel(
                sample_id=sample.sample_id,
                batch_id=sample.batch_id,
                source_id=sample.card.metadata.source_id,
                sample_digest=sample.sample_digest,
                primary_project_genre=sample.primary_project_genre,
                sample_json=sample.model_dump(mode="json"),
            ))
            return True

    async def list_samples(self, project_genre: str) -> list[ResearchSample]:
        async with self.sessions() as session:
            rows = await session.scalars(
                select(ResearchSampleModel).where(
                    or_(
                        ResearchSampleModel.primary_project_genre == project_genre,
                        cast(ResearchSampleModel.sample_json, JSONB)[
                            "secondary_project_genres"
                        ].contains([project_genre]),
                    )
                )
            )
            return [ResearchSample.model_validate(row.sample_json) for row in rows]

    async def next_version(self, project_genre: str) -> int:
        from sqlalchemy import func, select
        async with self.sessions() as session:
            value = await session.scalar(
                select(func.max(GenreKnowledgeVersionModel.version)).where(
                    GenreKnowledgeVersionModel.project_genre == project_genre
                )
            )
            return int(value or 0) + 1

    async def add_package(self, package: GenreKnowledgePackage) -> None:
        async with self.sessions() as session, session.begin():
            session.add(GenreKnowledgeVersionModel(
                knowledge_version_id=package.knowledge_version_id,
                project_genre=package.project_genre,
                version=package.version,
                status=package.status,
                package_json=package.model_dump(mode="json"),
                retrieval_text=package.retrieval_text,
            ))
            for term, weight in package.opening_pattern_counts.items():
                session.add(GenreTermModel(
                    knowledge_version_id=package.knowledge_version_id,
                    project_genre=package.project_genre,
                    term=normalize_term(term),
                    term_type="opening_pattern",
                    weight=weight,
                ))
            for term, weight in package.mechanism_counts.items():
                session.add(GenreTermModel(
                    knowledge_version_id=package.knowledge_version_id,
                    project_genre=package.project_genre,
                    term=normalize_term(term),
                    term_type="highlight_mechanism",
                    weight=weight,
                ))

    async def list_packages(self, project_genre: str, approved_only: bool = True) -> list[GenreKnowledgePackage]:
        async with self.sessions() as session:
            stmt = select(GenreKnowledgeVersionModel).where(
                GenreKnowledgeVersionModel.project_genre == project_genre
            )
            if approved_only:
                stmt = stmt.where(GenreKnowledgeVersionModel.status == "approved")
            stmt = stmt.order_by(GenreKnowledgeVersionModel.version.desc())
            if approved_only:
                stmt = stmt.limit(1)
            rows = await session.scalars(stmt)
            return [GenreKnowledgePackage.model_validate(row.package_json) for row in rows]

    async def review_package(self, version_id: str, decision: str) -> GenreKnowledgePackage | None:
        async with self.sessions() as session, session.begin():
            row = await session.get(GenreKnowledgeVersionModel, version_id)
            if row is None:
                return None
            package = GenreKnowledgePackage.model_validate(row.package_json)
            updated = package.model_copy(update={
                "status": "approved" if decision == "approve" else "rejected",
            })
            row.status = updated.status
            row.package_json = updated.model_dump(mode="json")
            return updated
