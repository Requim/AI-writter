"""Strict loader for packaged or externally hot-swappable UTF-8 templates."""

import hashlib
from contextvars import ContextVar
from importlib.resources import files
from pathlib import Path, PurePosixPath
from string import Template
from typing import Any

from config import settings
from application.prompts.version import PROMPT_VERSION

_TEMPLATE_PACKAGE = "application.prompts.templates"
_last_valid: dict[str, tuple[str, str, str | None]] = {}
_active_snapshot: ContextVar[dict[str, str] | None] = ContextVar(
    "active_prompt_snapshot", default=None
)


def set_prompt_snapshot(snapshot: dict[str, str] | None):
    """在单次节点调用范围内绑定不可变模板内容。"""
    return _active_snapshot.set(snapshot)


def reset_prompt_snapshot(token: Any) -> None:
    _active_snapshot.reset(token)


def _validate_template_name(name: str) -> PurePosixPath:
    if "\\" in name:
        raise ValueError(f"非法提示词模板路径: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or path.suffix != ".txt":
        raise ValueError(f"非法提示词模板路径: {name}")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法提示词模板路径: {name}")
    return path


def _external_path(name: str) -> Path | None:
    if not settings.PROMPT_ROOT:
        return None
    root = Path(settings.PROMPT_ROOT).expanduser().resolve()
    candidate = (root / Path(*_validate_template_name(name).parts)).resolve()
    if root != candidate and root not in candidate.parents:
        raise ValueError(f"提示词模板超出配置目录: {name}")
    return candidate


def _read_builtin(name: str) -> str:
    path = _validate_template_name(name)
    resource = files(_TEMPLATE_PACKAGE).joinpath(*path.parts)
    if not resource.is_file():
        raise FileNotFoundError(f"提示词模板不存在: {name}")
    return resource.read_text(encoding="utf-8")


def load_prompt_template(name: str) -> str:
    """读取外部模板；更新失败时保留上一份有效内容并内置兜底。"""
    _validate_template_name(name)
    snapshot = _active_snapshot.get()
    if snapshot is not None and name in snapshot:
        return snapshot[name]
    external = _external_path(name)
    if external and external.is_file():
        try:
            content = external.read_text(encoding="utf-8")
            if not Template(content).is_valid():
                raise ValueError("模板包含非法占位符")
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            _last_valid[name] = (content, digest, str(external))
            return content
        except (OSError, UnicodeError, ValueError):
            if name in _last_valid and _last_valid[name][2] == str(external):
                return _last_valid[name][0]
    content = _read_builtin(name)
    _last_valid[name] = (
        content,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
        None,
    )
    return content


def prompt_manifest(
    names: list[str] | None = None, *, include_content: bool = False
) -> dict[str, Any]:
    """生成可写入 checkpoint 的模板版本和内容摘要。"""
    if names is None:
        root = files(_TEMPLATE_PACKAGE)
        names = [
            str(item.relative_to(root)).replace("\\", "/")
            for item in root.rglob("*.txt")
        ]
    entries = {}
    for name in sorted(set(names)):
        load_prompt_template(name)
        entries[name] = _last_valid[name][1]
    digest = hashlib.sha256(
        "".join(f"{name}:{entries[name]}\n" for name in entries).encode("utf-8")
    ).hexdigest()
    result: dict[str, Any] = {
        "version": f"{PROMPT_VERSION}:{digest[:12]}",
        "templates": entries,
    }
    if include_content:
        result["snapshot"] = {
            name: load_prompt_template(name) for name in sorted(entries)
        }
    return result


def render_prompt(
    name: str, /, *, include_active_rules: bool = True, **values: Any
) -> str:
    """严格渲染提示词；缺少占位变量时直接抛出异常。"""
    substitutions = {key: str(value) for key, value in values.items()}
    substitutions.setdefault("PROMPT_VERSION", PROMPT_VERSION)
    template = Template(load_prompt_template(name))
    if not template.is_valid():
        raise ValueError(f"模板 {name} 包含非法占位符")
    try:
        rendered = template.substitute(substitutions)
        if not include_active_rules:
            return rendered
        from application.creative.runtime import active_creative_rules
        return rendered + active_creative_rules.get()
    except KeyError as exc:
        raise ValueError(f"模板 {name} 缺少变量: {exc.args[0]}") from exc
