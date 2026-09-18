from app.metrics import Metrics, _percentile


def test_percentile_basic():
    values = [float(i) for i in range(1, 101)]  # 1..100
    assert _percentile(values, 50) == 50.5
    assert _percentile(values, 95) == 95.05
    assert _percentile([], 95) == 0.0
    assert _percentile([42.0], 95) == 42.0


def test_metrics_counts_and_snapshot():
    m = Metrics(window_s=60)
    m.record_request(10.0)
    m.record_request(20.0, healed=True, drift=True)
    m.record_request(30.0, error=True)
    m.set_simulated_users(200)

    snap = m.snapshot()
    assert snap["requests_total"] == 3
    assert snap["heals_applied"] == 1
    assert snap["drift_caught"] == 1
    assert snap["errors_total"] == 1
    assert snap["simulated_users"] == 200
    assert snap["simulated"] is True
    assert snap["p95_latency_ms"] >= snap["p50_latency_ms"] > 0
    assert snap["requests_per_min"] > 0


def test_set_simulated_users_never_negative():
    m = Metrics(window_s=60)
    m.set_simulated_users(-5)
    assert m.snapshot()["simulated_users"] == 0
