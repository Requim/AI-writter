"""滚动战术计划与章节执行契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


TACTICAL_SCHEMA_VERSION = 1
MAX_TACTICAL_CHAPTERS = 7

_SLOT_CONTRACT_FIELDS = frozenset(
    {
        "arc_ids",
        "detail_level",
        "must_happen",
        "obligations",
        "payoff_ids",
        "payoff_requirements",
        "planned_state_delta",
        "setup_ids",
        "setup_requirements",
        "slot_contract",
        "status",
        "story_function",
        "target_words",
        "volume_id",
    }
)


class TacticalPlanValidationError(ValueError):
    """战术计划或执行契约未通过确定性校验。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("；".join(errors))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc_now()


def _coverage_map(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, int] = {}
    for key, scene_index in value.items():
        normalized[str(key)] = _scene_index(scene_index)
    return normalized


def _scene_index(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def chapter_slot_ref(chapter_number: int) -> str:
    if chapter_number < 1:
        raise ValueError("章节号必须大于等于 1")
    return f"ch{chapter_number}"


def obligation_id(chapter_number: int, index: int) -> str:
    """返回稳定的必发事件 ID；index 使用从 1 开始的序号。"""
    if chapter_number < 1 or index < 1:
        raise ValueError("章节号和必发事件序号必须大于等于 1")
    return f"ch{chapter_number}:must:{index}"


def state_delta_id(chapter_number: int) -> str:
    return f"{chapter_slot_ref(chapter_number)}:state_delta"


def setup_coverage_id(chapter_number: int, setup_id: str) -> str:
    return f"{chapter_slot_ref(chapter_number)}:setup:{setup_id}"


def payoff_coverage_id(chapter_number: int, payoff_id: str) -> str:
    return f"{chapter_slot_ref(chapter_number)}:payoff:{payoff_id}"


@dataclass(frozen=True)
class TacticalBeat:
    chapter_number: int
    slot_ref: str
    tactical_goal: str
    approach: str
    bridge_from_previous: str
    pressure_escalation: str
    exit_hook: str
    pacing: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TacticalBeat:
        overwritten = sorted(_SLOT_CONTRACT_FIELDS.intersection(payload))
        if overwritten:
            names = ", ".join(overwritten)
            raise TacticalPlanValidationError([f"战术节拍不得改写槽位字段：{names}"])
        return cls(
            chapter_number=int(payload.get("chapter_number", 0) or 0),
            slot_ref=str(payload.get("slot_ref") or ""),
            tactical_goal=str(payload.get("tactical_goal") or ""),
            approach=str(payload.get("approach") or ""),
            bridge_from_previous=str(payload.get("bridge_from_previous") or ""),
            pressure_escalation=str(payload.get("pressure_escalation") or ""),
            exit_hook=str(payload.get("exit_hook") or ""),
            pacing=str(payload.get("pacing") or ""),
        )


@dataclass
class TacticalWindow:
    novel_plan_version: int
    story_state_revision: int
    start_chapter: int
    end_chapter: int
    volume_id: str
    window_objective: str
    beats: list[TacticalBeat]
    schema_version: int = TACTICAL_SCHEMA_VERSION
    version: int = 0
    source: str = "chapter_refresh"
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload

    def assert_valid(self) -> None:
        errors = validate_tactical_window_shape(self)
        if errors:
            raise TacticalPlanValidationError(errors)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> TacticalWindow:
        beats = payload.get("beats") or []
        return cls(
            novel_plan_version=int(payload.get("novel_plan_version", 0) or 0),
            story_state_revision=int(payload.get("story_state_revision", 0) or 0),
            start_chapter=int(payload.get("start_chapter", 0) or 0),
            end_chapter=int(payload.get("end_chapter", 0) or 0),
            volume_id=str(payload.get("volume_id") or ""),
            window_objective=str(payload.get("window_objective") or ""),
            beats=[TacticalBeat.from_dict(dict(item)) for item in beats],
            schema_version=int(payload.get("schema_version", TACTICAL_SCHEMA_VERSION)),
            version=int(payload.get("version", 0) or 0),
            source=str(payload.get("source") or "chapter_refresh"),
            created_at=_parse_datetime(payload.get("created_at")),
        )


@dataclass(frozen=True)
class ChapterExecutionContract:
    plan_version: int
    tactical_version: int
    chapter_number: int
    obligation_coverage: dict[str, int]
    state_delta_coverage: dict[str, int]
    setup_payoff_coverage: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def assert_valid(self) -> None:
        errors = validate_execution_contract_shape(self)
        if errors:
            raise TacticalPlanValidationError(errors)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChapterExecutionContract:
        setup_payoff = payload.get("setup_payoff_coverage")
        if setup_payoff is None:
            setup_payoff = payload.get("setup/payoff_coverage")
        return cls(
            plan_version=int(payload.get("plan_version", 0) or 0),
            tactical_version=int(payload.get("tactical_version", 0) or 0),
            chapter_number=int(payload.get("chapter_number", 0) or 0),
            obligation_coverage=_coverage_map(payload.get("obligation_coverage")),
            state_delta_coverage=_coverage_map(payload.get("state_delta_coverage")),
            setup_payoff_coverage=_coverage_map(setup_payoff),
        )


def _beat_errors(beat: TacticalBeat) -> list[str]:
    errors: list[str] = []
    if beat.chapter_number < 1:
        return ["战术节拍章节号必须大于等于 1"]
    if beat.slot_ref != chapter_slot_ref(beat.chapter_number):
        errors.append(f"第 {beat.chapter_number} 章槽位引用无效")
    narrative = (
        beat.tactical_goal,
        beat.approach,
        beat.bridge_from_previous,
        beat.pressure_escalation,
        beat.exit_hook,
        beat.pacing,
    )
    if not all(value.strip() for value in narrative):
        errors.append(f"第 {beat.chapter_number} 章战术字段不完整")
    return errors


def validate_tactical_window_shape(window: TacticalWindow) -> list[str]:
    errors: list[str] = []
    if window.schema_version != TACTICAL_SCHEMA_VERSION:
        errors.append(f"战术计划 schema_version 必须为 {TACTICAL_SCHEMA_VERSION}")
    if window.version < 0 or window.novel_plan_version < 1:
        errors.append("战术版本不得为负数且整书计划版本必须大于等于 1")
    if window.story_state_revision < 0:
        errors.append("故事状态版本不得为负数")
    if not window.source.strip() or len(window.source) > 30:
        errors.append("战术计划来源不能为空且不得超过 30 个字符")
    if not window.volume_id or not window.window_objective.strip():
        errors.append("战术窗口必须包含所属卷和窗口目标")
    span = window.end_chapter - window.start_chapter + 1
    if window.start_chapter < 1 or not 1 <= span <= MAX_TACTICAL_CHAPTERS:
        errors.append("战术窗口必须包含 1 到 7 个连续章节")
    expected = list(range(window.start_chapter, window.end_chapter + 1))
    if [beat.chapter_number for beat in window.beats] != expected:
        errors.append("战术节拍必须按章节连续且完整覆盖窗口")
    for beat in window.beats:
        errors.extend(_beat_errors(beat))
    return list(dict.fromkeys(errors))


def _coverage_errors(name: str, coverage: dict[str, int]) -> list[str]:
    if any(not key.strip() or scene_index < 1 for key, scene_index in coverage.items()):
        return [f"{name}不得包含空 ID，且 scene_index 必须大于等于 1"]
    return []


def validate_execution_contract_shape(
    contract: ChapterExecutionContract,
) -> list[str]:
    errors: list[str] = []
    if contract.plan_version < 1 or contract.tactical_version < 1:
        errors.append("执行契约的整书与战术版本必须大于等于 1")
    if contract.chapter_number < 1:
        errors.append("执行契约章节号必须大于等于 1")
    errors.extend(_coverage_errors("必发事件覆盖", contract.obligation_coverage))
    errors.extend(_coverage_errors("状态变化覆盖", contract.state_delta_coverage))
    errors.extend(_coverage_errors("伏笔覆盖", contract.setup_payoff_coverage))
    return errors
