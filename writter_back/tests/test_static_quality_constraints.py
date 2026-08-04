"""本轮改动的代码复杂度与提示词资源静态门禁。"""

from __future__ import annotations

import ast
from pathlib import Path
from string import Template

import pytest

from application.prompts.template_loader import render_prompt


BACKEND_ROOT = Path(__file__).parents[1]
TEMPLATE_ROOT = BACKEND_ROOT / "application" / "prompts" / "templates"
SOURCE_ROOTS = ("api", "application", "infrastructure", "service", "scripts", "tests")
NESTING_NODES = (
    ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.TryStar,
    ast.With, ast.AsyncWith, ast.Match,
)

# 仅允许本轮开始前已存在且未触达的历史函数；键为明确文件与限定函数名。
FROZEN_FUNCTION_VIOLATIONS = {
    ("api/routers/novel_router.py", "update_chapter"),
    ("application/agents/memory_retrieval_node.py", "memory_retrieval_node"),
    ("infrastructure/database/identity_repository.py", "IdentityRepository.reserve_quota"),
    ("infrastructure/database/repository.py", "PostgresNovelRepository.find_by_id_with_chapters"),
    ("infrastructure/database/repository.py", "PostgresNovelRepository.replace_chapter"),
    ("infrastructure/llm/openai_adapter.py", "OpenAIAdapter._stream_structured_response"),
    ("scripts/backfill_novel_metadata.py", "main"),
    ("tests/test_continuity.py", "test_persist_node_commits_all_continuity_artifacts_together"),
}

# 仅允许已确认不属于提示词的历史长字符串；键为明确文件、所属符号与行号。
FROZEN_LONG_STRINGS: set[tuple[str, str, int]] = set()


def _python_paths() -> list[Path]:
    paths = [path for root in SOURCE_ROOTS for path in (BACKEND_ROOT / root).rglob("*.py")]
    return sorted(path for path in paths if "__pycache__" not in path.parts)


def _qualified_functions(tree: ast.AST) -> list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = []

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                current = (*parents, child.name)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((".".join(current), child))
                visit(child, current)
            else:
                visit(child, parents)

    visit(tree)
    return found


def _function_line_count(node: ast.FunctionDef | ast.AsyncFunctionDef, lines: list[str]) -> int:
    selected = lines[node.lineno - 1 : node.end_lineno]
    return sum(bool(line.strip()) and not line.lstrip().startswith("#") for line in selected)


def _max_nesting(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    def walk(current: ast.AST, depth: int) -> int:
        maximum = depth
        for child in ast.iter_child_nodes(current):
            if child is not node and isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            child_depth = depth + int(isinstance(child, NESTING_NODES))
            maximum = max(maximum, walk(child, child_depth))
        return maximum

    return walk(node, 0)


def _owner_name(
    functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]],
    target: ast.Constant,
) -> str:
    owner = "<module>"
    for name, node in functions:
        if node.lineno <= target.lineno <= (node.end_lineno or node.lineno):
            owner = name
    return owner


def _template_variables(content: str) -> set[str]:
    variables: set[str] = set()
    for match in Template.pattern.finditer(content):
        name = match.group("named") or match.group("braced")
        if name:
            variables.add(name)
    return variables


def test_functions_respect_size_and_nesting_limits() -> None:
    violations: list[str] = []
    observed_frozen: set[tuple[str, str]] = set()
    for path in _python_paths():
        source = path.read_text(encoding="utf-8-sig")
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        tree = ast.parse(source, filename=str(path))
        for name, node in _qualified_functions(tree):
            key = (relative, name)
            lines = _function_line_count(node, source.splitlines())
            depth = _max_nesting(node)
            if lines <= 50 and depth <= 3:
                continue
            if key in FROZEN_FUNCTION_VIOLATIONS:
                observed_frozen.add(key)
            else:
                violations.append(f"{relative}:{node.lineno} {name} lines={lines} nesting={depth}")
    stale = sorted(FROZEN_FUNCTION_VIOLATIONS - observed_frozen)
    assert violations == [] and stale == [], f"new={violations}; stale_frozen={stale}"


def test_long_strings_live_only_in_prompt_templates() -> None:
    violations: list[str] = []
    for path in _python_paths():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        relative = path.relative_to(BACKEND_ROOT).as_posix()
        functions = _qualified_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            owner = _owner_name(functions, node)
            key = (relative, owner, node.lineno)
            if len(node.value) > 300 and key not in FROZEN_LONG_STRINGS:
                violations.append(f"{relative}:{node.lineno} {owner} chars={len(node.value)}")
    assert violations == []


def test_all_templates_are_utf8_and_strictly_renderable() -> None:
    paths = sorted(TEMPLATE_ROOT.rglob("*.txt"))
    assert paths
    for path in paths:
        content = path.read_text(encoding="utf-8")
        assert "\ufffd" not in content and Template(content).is_valid(), path
        values = {name: f"<{name}>" for name in _template_variables(content)}
        values.pop("PROMPT_VERSION", None)
        rendered = render_prompt(path.relative_to(TEMPLATE_ROOT).as_posix(), **values)
        assert not _template_variables(rendered), path


def test_each_template_rejects_a_missing_variable() -> None:
    for path in sorted(TEMPLATE_ROOT.rglob("*.txt")):
        content = path.read_text(encoding="utf-8")
        required = _template_variables(content) - {"PROMPT_VERSION"}
        if not required:
            continue
        omitted = sorted(required)[0]
        values = {name: name for name in required - {omitted}}
        with pytest.raises(ValueError, match="缺少变量"):
            render_prompt(path.relative_to(TEMPLATE_ROOT).as_posix(), **values)
