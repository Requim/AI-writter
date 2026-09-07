"""从持久公开事件生成不含小说正文的运行指标。"""
from collections import Counter, defaultdict
from typing import Any


def summarize_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    counters: Counter[str] = Counter({'events': 0, 'automatic_retries': 0, 'human_review_requests': 0,
        'fact_blocked': 0, 'fact_unknown': 0, 'errors': 0})
    durations: dict[str, list[float]] = defaultdict(list)
    for event in events:
        data = event.get('data') or {}
        counters['events'] += 1
        if data.get('status') == 'retrying':
            counters['automatic_retries'] += 1
        if event.get('type') == 'interrupt':
            _count_reviews(counters, data.get('interrupts') or [])
        if data.get('status') == 'measurement' and isinstance(data.get('duration_seconds'), (int, float)):
            durations[event.get('node') or 'unknown'].append(max(0.0, data['duration_seconds']))
        if event.get('type') == 'error':
            counters['errors'] += 1
    return {'counts': dict(counters), 'node_duration_seconds': {node: {'count': len(values),
        'mean': round(sum(values) / len(values), 4), 'max': max(values)} for node, values in durations.items()}}


def _count_reviews(counters: Counter[str], interrupts: list[Any]) -> None:
    for item in interrupts:
        if not isinstance(item, dict):
            continue
        counters['human_review_requests'] += 1
        if item.get('action') == 'fact_review_required':
            report = ((item.get('proposal') or {}).get('payload') or {}).get('report') or {}
            counters['fact_' + report.get('status', 'unknown')] += 1
