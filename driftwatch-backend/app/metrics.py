"""In-process live metrics for the pitch panel.

Everything here is counted in-process (one Render free instance) and only a small
snapshot is exposed; we deliberately do NOT write per-request rows to Redis so a load
test can't blow the free datastore's limits.

ALL user/traffic figures are SIMULATED (driven by the built-in load generator) and are
surfaced to the UI labelled as such - we never claim real users.

Tracked: requests/min, p95 latency, heals applied, drift caught, error rate, and the
number of SIMULATED concurrent users the load generator is currently running.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from .config import get_settings

settings = get_settings()


class Metrics:
    def __init__(self, window_s: int) -> None:
        self._window_s = window_s
        self._lock = threading.Lock()
        # (timestamp, latency_ms) samples within the rolling window.
        self._samples: deque[tuple[float, float]] = deque()
        self.requests_total = 0
        self.errors_total = 0
        self.heals_applied = 0
        self.drift_caught = 0
        self.simulated_users = 0
        self._started = time.time()

    def _evict(self, now: float) -> None:
        cutoff = now - self._window_s
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def record_request(
        self, latency_ms: float, *, error: bool = False, healed: bool = False, drift: bool = False
    ) -> None:
        now = time.time()
        with self._lock:
            self.requests_total += 1
            if error:
                self.errors_total += 1
            if healed:
                self.heals_applied += 1
            if drift:
                self.drift_caught += 1
            self._samples.append((now, latency_ms))
            self._evict(now)

    def set_simulated_users(self, n: int) -> None:
        with self._lock:
            self.simulated_users = max(0, int(n))

    def snapshot(self) -> dict:
        now = time.time()
        with self._lock:
            self._evict(now)
            latencies = sorted(l for _, l in self._samples)
            count_window = len(latencies)
            p95 = _percentile(latencies, 95)
            p50 = _percentile(latencies, 50)
            # requests/min = window count scaled to 60s.
            span = min(self._window_s, max(1.0, now - self._started))
            req_per_min = (count_window / span) * 60.0
            return {
                "simulated_users": self.simulated_users,
                "requests_per_min": round(req_per_min, 1),
                "requests_total": self.requests_total,
                "p50_latency_ms": round(p50, 1),
                "p95_latency_ms": round(p95, 1),
                "heals_applied": self.heals_applied,
                "drift_caught": self.drift_caught,
                "errors_total": self.errors_total,
                "error_rate_pct": round(
                    (self.errors_total / self.requests_total * 100.0) if self.requests_total else 0.0,
                    2,
                ),
                "window_s": self._window_s,
                "simulated": True,  # UI must label all traffic/user numbers SIMULATED
                "ts": now,
            }


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = k - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


_metrics = Metrics(get_settings().metrics_window_s)


def metrics() -> Metrics:
    return _metrics
