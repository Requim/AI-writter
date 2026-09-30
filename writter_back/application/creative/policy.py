"""创作选择与调整的确定性规则，模型评分不代表市场证据。"""

from typing import Any

from application.creative.errors import CreativePause

WEIGHTS = {"continue_reading": .4, "clarity": .2, "payoff": .2, "sustainability": .2}


def window_number(chapter: int) -> int:
    if chapter < 1:
        raise ValueError("章节号从1开始")
    return (chapter - 1) // 5


def select_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """先执行硬门槛，再稳定排序；调用方负责且仅允许一次修复。"""
    eligible = [c for c in candidates if c.get("quality_pass") is True and c.get("hard_constraints_pass") is True]
    if not eligible:
        raise CreativePause("no_eligible_candidate", "全部候选未通过质量或硬约束门槛")
    for candidate in eligible:
        scores = candidate.get("scores", {})
        if any(type(scores.get(k)) not in (int, float) or not 0 <= scores[k] <= 100 for k in WEIGHTS):
            raise ValueError("候选评分必须为0-100的有效数值")
        if candidate.get("evaluation_source") != "blind_pilot_and_independent_plan":
            raise ValueError("候选排序缺少隔离试读或独立规划评价")
    return sorted(eligible, key=lambda c: (
        -sum(c["scores"][k] * weight for k, weight in WEIGHTS.items()),
        c.get("repetition_risk", 100), c.get("complexity", 100), c["index"],
    ))[0]


def validate_engine(engine: dict[str, Any]) -> list[str]:
    required = (
        "conflict_mechanism", "consequences", "escalation_dimensions",
        "cost_constraints", "variation_factors", "exhaustion_risks",
    )
    errors = [key for key in required if not engine.get(key)]
    nodes = engine.get("conflict_nodes", [])
    if not isinstance(nodes, list):
        return [*errors, "conflict_nodes 必须为数组"]
    if len(nodes) != 10:
        errors.append("conflict_nodes 必须为10个")
    for node in nodes:
        if not isinstance(node, dict) or any(not node.get(key) for key in ("problem", "choice", "cost", "consequence", "variation")):
            errors.append("冲突节点缺少问题、选择、代价、后果或变化")
    return errors


def choose_route(routes: list[dict[str, Any]]) -> dict[str, Any]:
    """没有可行人物选择时明确拒绝，而不是强迫人物执行大纲。"""
    if len(routes) > 2:
        raise ValueError("关键转折最多比较两条路线")
    if any(not isinstance(r, dict) for r in routes):
        raise ValueError("路线必须为结构化对象")
    feasible = [r for r in routes if r.get("feasible") is True and r.get("hard_constraints_pass") is True]
    for route in feasible:
        if any(not route.get(key) for key in ("motivation", "opponent_response", "cost", "consequence")):
            raise ValueError("路线缺少动机、对手反应、代价或后果")
    return {"status": "feasible", "route": feasible[0]} if feasible else {"status": "no_feasible_route"}


def validate_replan(
    *, chapter: int, total: int, ending_changes: int, changes_ending: bool,
    accepted_windows: list[int], hard_constraints_changed: bool = False,
    archived_changed: bool = False, scale_changed: bool = False,
    locked_window_changed: bool = False,
) -> None:
    """补充既有计划CAS和锁定窗口校验，不代替其校验。"""
    if hard_constraints_changed or archived_changed or scale_changed or locked_window_changed:
        raise CreativePause("immutable_contract", "改纲触及用户硬设定、正文、规模或锁定窗口")
    if window_number(chapter) in accepted_windows:
        raise CreativePause("replan_window", "本五章窗口已接受一次结构性改纲")
    if changes_ending and (ending_changes >= 2 or chapter > total - 5):
        raise CreativePause("ending_frozen", "自动改结局次数已用尽或已进入最后五章")
