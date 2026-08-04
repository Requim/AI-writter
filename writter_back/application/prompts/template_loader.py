"""Strict loader for packaged UTF-8 prompt templates."""

from functools import lru_cache
from importlib.resources import files
from pathlib import PurePosixPath
from string import Template
from typing import Any

from application.prompts.version import PROMPT_VERSION


_TEMPLATE_PACKAGE = "application.prompts.templates"


def _validate_template_name(name: str) -> PurePosixPath:
    if "\\" in name:
        raise ValueError(f"非法提示词模板路径: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or path.suffix != ".txt":
        raise ValueError(f"非法提示词模板路径: {name}")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"非法提示词模板路径: {name}")
    return path


@lru_cache(maxsize=None)
def load_prompt_template(name: str) -> str:
    """按 UTF-8 读取已打包的提示词模板。"""
    path = _validate_template_name(name)
    resource = files(_TEMPLATE_PACKAGE).joinpath(*path.parts)
    if not resource.is_file():
        raise FileNotFoundError(f"提示词模板不存在: {name}")
    return resource.read_text(encoding="utf-8")


def render_prompt(name: str, /, **values: Any) -> str:
    """严格渲染提示词；缺少占位变量时直接抛出异常。"""
    substitutions = {key: str(value) for key, value in values.items()}
    substitutions.setdefault("PROMPT_VERSION", PROMPT_VERSION)
    template = Template(load_prompt_template(name))
    if not template.is_valid():
        raise ValueError(f"模板 {name} 包含非法占位符")
    try:
        return template.substitute(substitutions)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"模板 {name} 缺少变量: {missing}") from exc
