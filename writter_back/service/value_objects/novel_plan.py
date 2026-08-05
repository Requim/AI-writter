"""整书规划领域契约与确定性校验。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from math import ceil, isfinite
from typing import Any, Iterable


MIN_CHAPTERS = 1
MAX_CHAPTERS = 200
MIN_CHAPTER_WORDS = 3000
MAX_CHAPTER_WORDS = 7000
MAX_CHAPTERS_PER_VOLUME = 25
MAX_VOLUMES = 8
DEFAULT_TOLERANCE_RATIO = 0.1
DEFAULT_LOCK_WINDOW = 5
PLAN_SCHEMA_VERSION = 1

_PRESETS = (
    ("short", "短篇", 12, 50_400, 1),
    ("medium", "中篇", 36, 151_200, 2),
    ("long", "长篇", 80, 336_000, 4),
    ("epic", "超长篇", 150, 630_000, 6),
)


class NovelPlanValidationError(ValueError):
    """完整计划未通过确定性校验。"""

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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _target_volumes(target_chapters: int) -> int:
    return min(MAX_VOLUMES, max(1, ceil(target_chapters / MAX_CHAPTERS_PER_VOLUME)))


@dataclass
class ScaleContract:
    """由用户确认的整书规模硬约束与软目标。"""

    preset: str
    target_chapters: int
    target_total_words: int
    tolerance_ratio: float = DEFAULT_TOLERANCE_RATIO
    average_chapter_words: int = 0
    target_volumes: int = 0
    lock_window: int = DEFAULT_LOCK_WINDOW

    def __post_init__(self) -> None:
        self.average_chapter_words = self.average_chapter_words or round(
            self.target_total_words / max(self.target_chapters, 1)
        )
        self.target_volumes = self.target_volumes or _target_volumes(
            self.target_chapters
        )
        errors = _scale_errors(self)
        if errors:
            raise NovelPlanValidationError(errors)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScaleContract:
        return cls(
            preset=str(payload.get("preset") or "custom"),
            target_chapters=int(payload.get("target_chapters", 0) or 0),
            target_total_words=int(payload.get("target_total_words", 0) or 0),
            tolerance_ratio=float(
                payload.get("tolerance_ratio", DEFAULT_TOLERANCE_RATIO)
            ),
            average_chapter_words=int(payload.get("average_chapter_words", 0) or 0),
            target_volumes=int(payload.get("target_volumes", 0) or 0),
            lock_window=int(payload.get("lock_window", DEFAULT_LOCK_WINDOW)),
        )


@dataclass
class VolumePlan:
    volume_id: str
    title: str
    start_chapter: int
    end_chapter: int
    target_words: int
    opening_state: str = ""
    midpoint_turn: str = ""
    climax: str = ""
    ending_state: str = ""
    reader_promises: list[str] = field(default_factory=list)
    setup_ids: list[str] = field(default_factory=list)
    payoff_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VolumePlan:
        return cls(
            volume_id=str(payload.get("volume_id") or payload.get("id") or ""),
            title=str(payload.get("title") or ""),
            start_chapter=int(payload.get("start_chapter", 0) or 0),
            end_chapter=int(payload.get("end_chapter", 0) or 0),
            target_words=int(payload.get("target_words", 0) or 0),
            opening_state=str(payload.get("opening_state") or ""),
            midpoint_turn=str(payload.get("midpoint_turn") or ""),
            climax=str(payload.get("climax") or ""),
            ending_state=str(payload.get("ending_state") or ""),
            reader_promises=_string_list(payload.get("reader_promises")),
            setup_ids=_string_list(payload.get("setup_ids")),
            payoff_ids=_string_list(payload.get("payoff_ids")),
        )


@dataclass
class StoryArc:
    arc_id: str
    arc_type: str
    start_chapter: int
    end_chapter: int
    goal: str
    escalation_points: list[dict[str, Any]] = field(default_factory=list)
    resolution_condition: str = ""
    is_core: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StoryArc:
        return cls(
            arc_id=str(payload.get("arc_id") or payload.get("id") or ""),
            arc_type=str(payload.get("arc_type") or payload.get("type") or ""),
            start_chapter=int(payload.get("start_chapter", 0) or 0),
            end_chapter=int(payload.get("end_chapter", 0) or 0),
            goal=str(payload.get("goal") or ""),
            escalation_points=_dict_list(payload.get("escalation_points")),
            resolution_condition=str(payload.get("resolution_condition") or ""),
            is_core=bool(payload.get("is_core", False)),
        )


@dataclass
class ChapterSlot:
    chapter_number: int
    volume_id: str
    arc_ids: list[str]
    story_function: str
    must_happen: list[str]
    planned_state_delta: str
    target_words: int
    setup_ids: list[str] = field(default_factory=list)
    payoff_ids: list[str] = field(default_factory=list)
    detail_level: str = "skeleton"
    status: str = "planned"

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ChapterSlot:
        return cls(
            chapter_number=int(payload.get("chapter_number", 0) or 0),
            volume_id=str(payload.get("volume_id") or ""),
            arc_ids=_string_list(payload.get("arc_ids")),
            story_function=str(payload.get("story_function") or ""),
            must_happen=_string_list(payload.get("must_happen")),
            planned_state_delta=str(payload.get("planned_state_delta") or ""),
            target_words=int(payload.get("target_words", 0) or 0),
            setup_ids=_string_list(payload.get("setup_ids")),
            payoff_ids=_string_list(payload.get("payoff_ids")),
            detail_level=str(payload.get("detail_level") or "skeleton"),
            status=str(payload.get("status") or "planned"),
        )


@dataclass
class NovelPlan:
    scale: ScaleContract
    ending_contract: dict[str, Any]
    volumes: list[VolumePlan]
    arcs: list[StoryArc]
    chapter_slots: list[ChapterSlot]
    schema_version: int = PLAN_SCHEMA_VERSION
    version: int = 0
    source: str = "initial"
    created_at: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload

    def assert_valid(self) -> None:
        errors = validate_novel_plan(self)
        if errors:
            raise NovelPlanValidationError(errors)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> NovelPlan:
        return cls(
            scale=ScaleContract.from_dict(dict(payload.get("scale") or {})),
            ending_contract=dict(payload.get("ending_contract") or {}),
            volumes=[
                VolumePlan.from_dict(item) for item in (payload.get("volumes") or [])
            ],
            arcs=[StoryArc.from_dict(item) for item in (payload.get("arcs") or [])],
            chapter_slots=[
                ChapterSlot.from_dict(item)
                for item in (payload.get("chapter_slots") or [])
            ],
            schema_version=int(payload.get("schema_version", PLAN_SCHEMA_VERSION)),
            version=int(payload.get("version", 0) or 0),
            source=str(payload.get("source") or "initial"),
            created_at=_parse_datetime(payload.get("created_at")),
        )


@dataclass
class PlanExecution:
    chapter_number: int
    plan_version: int
    status: str
    actual_words: int
    fulfillment: dict[str, Any]
    drift_severity: str = "none"
    updated_at: datetime = field(default_factory=_utc_now)
    tactical_version: int | None = None

    def __post_init__(self) -> None:
        errors: list[str] = []
        if self.chapter_number < 1:
            errors.append("执行记录章节号必须大于等于 1")
        if self.plan_version < 1:
            errors.append("执行记录计划版本必须大于等于 1")
        if self.actual_words < 0:
            errors.append("执行记录实际字数不得为负数")
        if self.tactical_version is not None and self.tactical_version < 1:
            errors.append("执行记录战术版本必须大于等于 1")
        if self.drift_severity not in {"none", "minor", "major"}:
            errors.append("执行记录漂移等级无效")
        if not self.status:
            errors.append("执行记录状态不能为空")
        if errors:
            raise NovelPlanValidationError(errors)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["updated_at"] = self.updated_at.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PlanExecution:
        return cls(
            chapter_number=int(payload.get("chapter_number", 0) or 0),
            plan_version=int(payload.get("plan_version", 0) or 0),
            status=str(payload.get("status") or "pending"),
            actual_words=int(payload.get("actual_words", 0) or 0),
            fulfillment=dict(payload.get("fulfillment") or {}),
            drift_severity=str(payload.get("drift_severity") or "none"),
            updated_at=_parse_datetime(payload.get("updated_at")),
            tactical_version=(
                int(payload["tactical_version"])
                if payload.get("tactical_version") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class NovelPlanVersionSummary:
    """计划版本列表使用的轻量审计信息。"""

    version: int
    source: str
    trigger_chapter: int | None
    change_summary: str
    created_by_user_id: str | None
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = self.created_at.isoformat()
        return payload


def planning_options() -> dict[str, Any]:
    """返回创建接口与前端共用的权威规模选项。"""
    presets = [
        {
            "preset": key,
            "label": label,
            "target_chapters": chapters,
            "target_total_words": words,
            "target_volumes": volumes,
        }
        for key, label, chapters, words, volumes in _PRESETS
    ]
    return {
        "constraints": {
            "min_chapters": MIN_CHAPTERS,
            "max_chapters": MAX_CHAPTERS,
            "min_chapter_words": MIN_CHAPTER_WORDS,
            "max_chapter_words": MAX_CHAPTER_WORDS,
            "default_tolerance_ratio": DEFAULT_TOLERANCE_RATIO,
            "default_lock_window": DEFAULT_LOCK_WINDOW,
        },
        "presets": presets,
    }


def _scale_errors(scale: ScaleContract) -> list[str]:
    errors: list[str] = []
    allowed_presets = {item[0] for item in _PRESETS} | {"custom"}
    if scale.preset not in allowed_presets:
        errors.append("规模预设无效")
    if not MIN_CHAPTERS <= scale.target_chapters <= MAX_CHAPTERS:
        errors.append(f"总章节数必须在 {MIN_CHAPTERS} 到 {MAX_CHAPTERS} 之间")
    minimum = scale.target_chapters * MIN_CHAPTER_WORDS
    maximum = scale.target_chapters * MAX_CHAPTER_WORDS
    if not minimum <= scale.target_total_words <= maximum:
        errors.append("目标总字数必须落在章节数乘以单章字数上下限之间")
    if not 0 <= scale.tolerance_ratio <= 1:
        errors.append("总字数容差必须在 0 到 1 之间")
    if scale.target_volumes != _target_volumes(scale.target_chapters):
        errors.append("目标卷数必须按每卷最多 25 章计算")
    if scale.average_chapter_words != round(
        scale.target_total_words / max(scale.target_chapters, 1)
    ):
        errors.append("平均章字数必须由目标总字数和章节数计算")
    if scale.lock_window != DEFAULT_LOCK_WINDOW:
        errors.append(f"锁定窗口固定为 {DEFAULT_LOCK_WINDOW} 章")
    return errors


def _volume_errors(plan: NovelPlan) -> list[str]:
    errors: list[str] = []
    if len(plan.volumes) != plan.scale.target_volumes:
        errors.append("分卷数量与规模契约不一致")
    if plan.volumes != sorted(plan.volumes, key=lambda item: item.start_chapter):
        errors.append("分卷必须按起始章节升序排列")
    expected_start = 1
    seen: set[str] = set()
    for volume in sorted(plan.volumes, key=lambda item: item.start_chapter):
        if not volume.volume_id or volume.volume_id in seen:
            errors.append("分卷 ID 不能为空且不得重复")
        seen.add(volume.volume_id)
        if volume.start_chapter != expected_start:
            errors.append("分卷章节范围存在空洞或重叠")
        if not volume.start_chapter <= volume.end_chapter:
            errors.append(f"分卷 {volume.volume_id} 的章节范围无效")
        if volume.end_chapter - volume.start_chapter + 1 > MAX_CHAPTERS_PER_VOLUME:
            errors.append(f"分卷 {volume.volume_id} 超过 25 章")
        if not all(
            (
                volume.opening_state,
                volume.midpoint_turn,
                volume.climax,
                volume.ending_state,
            )
        ):
            errors.append(f"分卷 {volume.volume_id} 缺少完整的叙事状态或转折")
        expected_start = volume.end_chapter + 1
    if expected_start != plan.scale.target_chapters + 1:
        errors.append("分卷未完整覆盖全书章节")
    if sum(volume.target_words for volume in plan.volumes) != plan.scale.target_total_words:
        errors.append("分卷字数预算总和与目标总字数不一致")
    return errors


def _arc_errors(plan: NovelPlan) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for arc in plan.arcs:
        if not arc.arc_id or arc.arc_id in seen:
            errors.append("剧情弧 ID 不能为空且不得重复")
        seen.add(arc.arc_id)
        if not 1 <= arc.start_chapter <= arc.end_chapter <= plan.scale.target_chapters:
            errors.append(f"剧情弧 {arc.arc_id} 的章节范围无效")
        if not arc.arc_type or not arc.goal or not arc.resolution_condition:
            errors.append(f"剧情弧 {arc.arc_id} 缺少类型、目标或解决条件")
        if not arc.escalation_points:
            errors.append(f"剧情弧 {arc.arc_id} 缺少升级节点")
        for point in arc.escalation_points:
            chapter = int(point.get("chapter_number", 0) or 0)
            if not arc.start_chapter <= chapter <= arc.end_chapter:
                errors.append(f"剧情弧 {arc.arc_id} 的升级节点越界")
    if not any(
        arc.is_core and arc.end_chapter == plan.scale.target_chapters
        for arc in plan.arcs
    ):
        errors.append("至少一条核心剧情弧必须在最终章闭合")
    return errors


def _slot_errors(plan: NovelPlan) -> list[str]:
    errors: list[str] = []
    expected = list(range(1, plan.scale.target_chapters + 1))
    actual = sorted(slot.chapter_number for slot in plan.chapter_slots)
    if actual != expected:
        errors.append("章节骨架必须唯一且完整覆盖全部章节")
    volumes = {volume.volume_id: volume for volume in plan.volumes}
    arcs = {arc.arc_id: arc for arc in plan.arcs}
    for slot in plan.chapter_slots:
        volume = volumes.get(slot.volume_id)
        if volume is None or not volume.start_chapter <= slot.chapter_number <= volume.end_chapter:
            errors.append(f"第 {slot.chapter_number} 章未落入声明的分卷")
        if set(slot.arc_ids) - arcs.keys():
            errors.append(f"第 {slot.chapter_number} 章引用了不存在的剧情弧")
        if any(
            arc_id in arcs
            and not arcs[arc_id].start_chapter
            <= slot.chapter_number
            <= arcs[arc_id].end_chapter
            for arc_id in slot.arc_ids
        ):
            errors.append(f"第 {slot.chapter_number} 章引用了范围外的剧情弧")
        if not MIN_CHAPTER_WORDS <= slot.target_words <= MAX_CHAPTER_WORDS:
            errors.append(f"第 {slot.chapter_number} 章目标字数越界")
        if not slot.story_function or not slot.must_happen:
            errors.append(f"第 {slot.chapter_number} 章缺少章节功能或必发事件")
        if not slot.planned_state_delta:
            errors.append(f"第 {slot.chapter_number} 章缺少预期状态变化")
        if slot.detail_level not in {"skeleton", "detailed"}:
            errors.append(f"第 {slot.chapter_number} 章细化层级无效")
    if sum(slot.target_words for slot in plan.chapter_slots) != plan.scale.target_total_words:
        errors.append("章节目标字数总和与整书目标不一致")
    return errors


def _volume_slot_word_errors(plan: NovelPlan) -> list[str]:
    totals = {volume.volume_id: 0 for volume in plan.volumes}
    for slot in plan.chapter_slots:
        if slot.volume_id in totals:
            totals[slot.volume_id] += slot.target_words
    return [
        f"分卷 {volume.volume_id} 的字数预算与章节槽位不一致"
        for volume in plan.volumes
        if totals.get(volume.volume_id) != volume.target_words
    ]


def _foreshadowing_errors(slots: Iterable[ChapterSlot]) -> list[str]:
    setup_at: dict[str, int] = {}
    payoff_at: dict[str, int] = {}
    for slot in slots:
        for setup_id in slot.setup_ids:
            setup_at.setdefault(setup_id, slot.chapter_number)
        for payoff_id in slot.payoff_ids:
            payoff_at.setdefault(payoff_id, slot.chapter_number)
    errors = [f"伏笔 {key} 没有安排回收" for key in setup_at.keys() - payoff_at.keys()]
    errors.extend(f"回收项 {key} 没有对应伏笔" for key in payoff_at.keys() - setup_at.keys())
    errors.extend(
        f"伏笔 {key} 的回收早于埋设"
        for key in setup_at.keys() & payoff_at.keys()
        if payoff_at[key] <= setup_at[key]
    )
    return errors


def validate_novel_plan(plan: NovelPlan) -> list[str]:
    """返回适合反馈给模型重试的全部确定性错误。"""
    errors = _scale_errors(plan.scale)
    if plan.schema_version != PLAN_SCHEMA_VERSION:
        errors.append(f"计划 schema_version 必须为 {PLAN_SCHEMA_VERSION}")
    if not plan.source or len(plan.source) > 30:
        errors.append("计划来源不能为空且不得超过 30 个字符")
    if not plan.ending_contract:
        errors.append("整书计划必须包含结局契约")
    errors.extend(_volume_errors(plan))
    errors.extend(_arc_errors(plan))
    errors.extend(_slot_errors(plan))
    errors.extend(_volume_slot_word_errors(plan))
    errors.extend(_foreshadowing_errors(plan.chapter_slots))
    return list(dict.fromkeys(errors))


def validate_plan_transition(
    previous: NovelPlan, candidate: NovelPlan, completed_chapters: int
) -> list[str]:
    """校验重规划没有触碰已完成章节及其后锁定窗口。"""
    locked_through = min(
        previous.scale.target_chapters,
        completed_chapters + previous.scale.lock_window,
    )
    errors: list[str] = []
    if candidate.scale.target_chapters < locked_through:
        errors.append("缩减后的总章节数不得小于锁定边界")
    previous_slots = {slot.chapter_number: asdict(slot) for slot in previous.chapter_slots}
    candidate_slots = {slot.chapter_number: asdict(slot) for slot in candidate.chapter_slots}
    changed = [
        number
        for number in range(1, locked_through + 1)
        if previous_slots.get(number) != candidate_slots.get(number)
    ]
    if changed:
        errors.append(f"重规划修改了锁定章节：{changed}")
    return errors


def _normalized_weights(weights: Iterable[float]) -> list[float]:
    normalized = [float(weight) for weight in weights]
    if not normalized or any(not isfinite(weight) or weight <= 0 for weight in normalized):
        raise ValueError("章节强度权重必须是有限正数")
    return normalized


def _allocate_excess(excess: int, weights: list[float], capacity: int) -> list[int]:
    allocated = [0] * len(weights)
    active = set(range(len(weights)))
    remaining = excess
    while active and remaining:
        weight_sum = sum(weights[index] for index in active)
        raw = {index: remaining * weights[index] / weight_sum for index in active}
        saturated = [index for index in active if raw[index] >= capacity - allocated[index]]
        if saturated:
            for index in saturated:
                granted = capacity - allocated[index]
                allocated[index] += granted
                remaining -= granted
                active.remove(index)
            continue
        floors = {index: int(raw[index]) for index in active}
        for index, granted in floors.items():
            allocated[index] += granted
            remaining -= granted
        ranked = sorted(active, key=lambda index: (-(raw[index] - floors[index]), index))
        for index in ranked[:remaining]:
            allocated[index] += 1
        remaining = 0
    return allocated


def allocate_word_targets(target_total_words: int, weights: Iterable[float]) -> list[int]:
    """按最大余数法分配章字数，并保证总和精确闭合。"""
    normalized = _normalized_weights(weights)
    minimum = len(normalized) * MIN_CHAPTER_WORDS
    maximum = len(normalized) * MAX_CHAPTER_WORDS
    if not minimum <= target_total_words <= maximum:
        raise ValueError("目标总字数超出章节数量可分配范围")
    excess = target_total_words - minimum
    additions = _allocate_excess(
        excess, normalized, MAX_CHAPTER_WORDS - MIN_CHAPTER_WORDS
    )
    targets = [MIN_CHAPTER_WORDS + addition for addition in additions]
    if sum(targets) != target_total_words:
        raise RuntimeError("章节字数分配未能精确闭合")
    return targets
