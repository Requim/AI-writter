"""恢复退避必须有上限，不能无限隐藏失败。"""
from application.reconciliation_policy import deferred_request, recovery_ready


def test_recovery_backoff_then_dead_letter_preserves_request(monkeypatch):
    monkeypatch.setattr('application.reconciliation_policy.time.time', lambda: 1000)
    request = {'next_index': 3, 'discard_from_index': 2, 'is_completed': False}
    first = deferred_request(request, 'checkpoint_unavailable')
    assert first['_recovery']['next_attempt_at'] == 1005
    assert not recovery_ready(first)
    current = first
    for _ in range(4):
        current = deferred_request(current, 'checkpoint_unavailable')
    assert current['_recovery']['status'] == 'dead_letter'
    assert current['next_index'] == 3
    monkeypatch.setattr('application.reconciliation_policy.time.time', lambda: 99999)
    assert not recovery_ready(current)
    assert recovery_ready(request)
