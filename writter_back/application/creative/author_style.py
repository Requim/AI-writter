"""按来源与作用范围编译偏好，每次最多三组对照、合计四千字。"""

from typing import Any

from application.creative.errors import CreativePause
from service.value_objects.author_style import AuthorProfile, AuthorSample, StylePreference

PRECEDENCE = {"instruction": 0, "scene": 1, "book": 2, "genre": 3, "global": 4}


def _relevant(preference, task, novel_id, genre, scene_function):
    if task not in preference.tasks:
        return False
    if preference.novel_id is not None and str(preference.novel_id) != novel_id:
        return False
    if preference.genre and preference.genre != genre:
        return False
    return not preference.scene_function or preference.scene_function == scene_function


def validate_profile_sources(profile: AuthorProfile, samples: dict[str, dict]) -> None:
    """所有偏好必须回链作者确认的原创样例，事实和剧情修改不可学习成文风。"""
    for preference in profile.preferences:
        for sample_id in preference.sample_ids:
            raw = samples.get(str(sample_id))
            if raw is None:
                raise ValueError("偏好引用了不存在或跨租户的样例")
            sample = AuthorSample.model_validate(raw)
            if sample.category != "style":
                raise ValueError("事实修正和剧情调整不能作为审美偏好来源")
            if sample.scope == "book" and (sample.novel_id != preference.novel_id or preference.scope in {"genre", "global"}):
                raise ValueError("本书样例不能自动提升为题材或全局偏好")
            if sample.scope == "genre" and (preference.scope == "global" or sample.genre != preference.genre):
                raise ValueError("题材样例不得扩大作用范围")


def _select_preferences(preferences: list[StylePreference]) -> list[StylePreference]:
    selected = {}
    for preference in sorted(preferences, key=lambda p: (p.strength != "hard", PRECEDENCE[p.scope], p.preference_id)):
        previous = selected.get(preference.aspect)
        if previous and previous.strength == preference.strength == "hard" and previous.value != preference.value:
            raise CreativePause("style_hard_conflict", f"审美硬要求冲突：{preference.aspect}")
        if previous is None:
            selected[preference.aspect] = preference
    return list(selected.values())


def compile_style(
    profile: AuthorProfile | None, samples: dict[str, dict], *,
    task: str, novel_id: str, genre: str, scene_function: str = "",
    hard_requirements: dict[str, str] | None = None,
) -> dict[str, Any]:
    """输出本次实际应用的偏好标识和对照，不宣称无样例时已学会作者审美。"""
    if profile is None or not profile.preferences:
        return {"learned": False, "constraints": [], "examples": [], "applied_ids": []}
    validate_profile_sources(profile, samples)
    relevant = [p for p in profile.preferences if _relevant(p, task, novel_id, genre, scene_function)]
    hard = hard_requirements or {}
    relevant = [p for p in relevant if p.aspect not in hard or p.value == hard[p.aspect]]
    selected = _select_preferences(relevant)
    examples, seen, remaining = [], set(), 4000
    for preference in selected:
        for sample_id in preference.sample_ids:
            key = str(sample_id)
            if key in seen or len(examples) >= 3:
                continue
            sample = samples[key]
            text = "\n".join(str(sample.get(field, "")) for field in ("original", "revision", "judgment", "reason"))
            if len(text) > remaining:
                continue
            examples.append({"sample_id": key, "comparison": text})
            seen.add(key)
            remaining -= len(text)
    return {
        "learned": bool(selected),
        "constraints": [{"aspect": p.aspect, "value": p.value, "strength": p.strength, "reason": p.reason} for p in selected],
        "examples": examples, "applied_ids": [p.preference_id for p in selected],
    }
