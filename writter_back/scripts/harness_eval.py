"""离线评估入口，失败时退出非零，供CI作为发布门禁。"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from application.harness_evaluation import run_evaluation

parser = argparse.ArgumentParser()
parser.add_argument('--output', default='harness-evaluation.json')
args = parser.parse_args()
report = asyncio.run(run_evaluation(Path(__file__).resolve().parents[1] / 'evals' / 'fact_cases.json'))
Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'cases': report['cases'], 'passed': report['passed'], 'provider_calls': 0}))
raise SystemExit(0 if report['cases'] == report['passed'] else 1)
