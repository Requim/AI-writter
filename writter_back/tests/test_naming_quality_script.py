"""离线命名质量评测脚本的费用与输出边界。"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.evaluate_naming_quality import build_report, main, render_report


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "evaluate_naming_quality.py"
BANNED_CLIENTS = {"anthropic", "httpx", "langchain", "openai", "requests"}


def _import_roots() -> set[str]:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    direct = {
        alias.name.partition(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        (node.module or "").partition(".")[0]
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    return direct | imported_from


def test_default_mode_only_shows_help(capsys) -> None:
    assert main([]) == 0
    output = capsys.readouterr().out
    assert "--evaluate" in output
    assert "候选总数" not in output


def test_script_has_no_model_or_network_client_imports() -> None:
    assert _import_roots().isdisjoint(BANNED_CLIENTS)


def test_explicit_evaluation_is_deterministic_and_offline() -> None:
    first = build_report(3, 4)
    second = build_report(3, 4)
    assert first == second
    assert first["external_calls"] == 0
    assert first["candidate_count"] == 12
    assert len(first["sample"]) == 12


def test_markdown_contains_server_attribution() -> None:
    report = build_report(1, 3)
    rendered = render_report(report, "markdown")
    assert "离线命名质量抽样" in rendered
    assert "| 姓名 | 作品 | 篇目 | 原句 |" in rendered
