"""显式启用的本地姓名抽样器；不连接模型或网络。"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from application.naming import build_candidate_pool


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线抽样检查古典出处姓名的分布与可读性")
    parser.add_argument("--evaluate", action="store_true", help="显式启用本地抽样")
    parser.add_argument("--seeds", type=int, default=100, help="固定种子数量")
    parser.add_argument("--candidates", type=int, default=6, help="每个种子的候选数量")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--output", type=Path, help="可选输出文件；默认打印到标准输出")
    return parser


def build_report(seed_count: int, candidates_per_seed: int) -> dict[str, Any]:
    """使用稳定种子构造纯本地质量报告。"""
    if seed_count < 1 or candidates_per_seed < 1:
        raise ValueError("种子数和每组候选数必须大于零")
    candidates = [
        candidate
        for seed in range(seed_count)
        for candidate in build_candidate_pool(
            tenant_id="offline-evaluation",
            novel_id=f"sample-{seed}",
            proposal_version=seed,
            prompt_version="offline",
            count=candidates_per_seed,
        )
    ]
    surname_counts = Counter(item.surname for item in candidates)
    work_counts = Counter(item.source.work for item in candidates)
    total = len(candidates)
    sample = [item.to_dict() for item in candidates[: min(30, total)]]
    return {
        "mode": "offline",
        "external_calls": 0,
        "seed_count": seed_count,
        "candidate_count": total,
        "unique_surnames": len(surname_counts),
        "max_surname_share": max(surname_counts.values(), default=0) / total,
        "surname_counts": dict(surname_counts.most_common()),
        "source_work_counts": dict(work_counts.most_common()),
        "sample": sample,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 离线命名质量抽样",
        "",
        f"- 固定种子：{report['seed_count']}",
        f"- 候选总数：{report['candidate_count']}",
        f"- 姓氏覆盖：{report['unique_surnames']}",
        f"- 单一姓氏最高占比：{report['max_surname_share']:.2%}",
        f"- 外部调用：{report['external_calls']}",
        "",
        "| 姓名 | 作品 | 篇目 | 原句 |",
        "|---|---|---|---|",
    ]
    for item in report["sample"]:
        source = item["source"]
        lines.append(f"| {item['name']} | {source['work']} | {source['chapter']} | {source['quote']} |")
    return "\n".join(lines)


def render_report(report: dict[str, Any], output_format: str) -> str:
    """把报告渲染为便于人工抽样的 JSON 或 Markdown。"""
    if output_format == "markdown":
        return _markdown(report)
    return json.dumps(report, ensure_ascii=False, indent=2)


def main(argv: Sequence[str] | None = None) -> int:
    """仅在显式传入 --evaluate 时执行本地评测。"""
    parser = _parser()
    args = parser.parse_args(argv)
    if not args.evaluate:
        parser.print_help()
        return 0
    report = build_report(args.seeds, args.candidates)
    rendered = render_report(report, args.format)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
