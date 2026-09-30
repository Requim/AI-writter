"""面向用途的白名单投影；不通过提示词请求模型自行隐藏秘密。"""

from copy import deepcopy
from typing import Any, Literal

CHARACTER_PUBLIC = frozenset({
    "character_id", "name", "role", "goal", "belief", "red_line",
    "abilities", "limits", "voice", "knowledge", "aliases", "allegiance",
})
READER_FIELDS = frozenset({
    "known", "misunderstandings", "expectations", "emotions", "fatigue",
    "paid_promises", "open_promises", "evidence", "through_chapter",
})


def project_context(
    view: Literal["author", "scene", "reader"], data: dict[str, Any],
    *, character_ids: tuple[str, ...] = (), allowed_information: tuple[str, ...] = (),
) -> dict[str, Any]:
    """投影入口只接收服务端已验证资料，未知字段默认不透出。"""
    if view == "author":
        return deepcopy(data)
    chapters = [
        {key: chapter[key] for key in ("id", "version", "chapter_index", "content") if key in chapter}
        for chapter in data.get("chapters", []) if chapter.get("status") == "completed"
    ]
    if view == "reader":
        state = data.get("reader_state") or {}
        return {"chapters": chapters, "reader_state": {
            key: deepcopy(value) for key, value in state.items() if key in READER_FIELDS
        }}
    if view != "scene":
        raise ValueError("不支持的创作上下文视图")
    selected = []
    for character in data.get("characters", []):
        if character.get("character_id") not in character_ids:
            continue
        selected.append({key: deepcopy(value) for key, value in character.items() if key in CHARACTER_PUBLIC})
    return {
        "characters": selected, "allowed_information": list(allowed_information),
        "action_requirements": deepcopy(data.get("action_requirements", [])),
        "chapter_intent": deepcopy(data.get("chapter_intent", {})),
        "archived_text": chapters,
        "style_constraints": deepcopy(data.get("style_constraints", [])),
        "hard_constraints": deepcopy(data.get("hard_constraints", [])),
    }
