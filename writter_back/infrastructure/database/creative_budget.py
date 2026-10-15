"""Book-bound operator authorization for an exceptional chapter allowance."""

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from infrastructure.database.creative_models import CreativeRecordModel


class OperatorChapterBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    chapter_limit: int = Field(ge=33, le=48)
    authorization: str = Field(min_length=1, max_length=500)


async def require_operator_chapter_budget(session, tenant, novel, chapter_limit):
    if chapter_limit <= 32:
        return
    record = await session.scalar(select(CreativeRecordModel).where(
        CreativeRecordModel.tenant_id == tenant, CreativeRecordModel.novel_id == novel,
        CreativeRecordModel.kind == "control", CreativeRecordModel.key == "operator_chapter_budget",
    ).order_by(CreativeRecordModel.version.desc()).limit(1))
    if record is None or record.source != "system" or record.status != "authorized":
        raise ValueError("超出默认单章预算需要本作品的运维授权")
    allowance = OperatorChapterBudget.model_validate(record.payload)
    if chapter_limit > allowance.chapter_limit:
        raise ValueError("单章预算超出本作品已授权的上限")
