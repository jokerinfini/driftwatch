"""SIMULATED load generator.

Spawns N concurrent "users", each looping watchlist refreshes through the FULL Mendr
egress path (envelope -> Mendr/shim -> heal -> contract) at a target rate. This is how
we can honestly pitch "hosted, load-tested to N SIMULATED users" - the number is exactly
the concurrency this generator is driving, never a claim of real users.

Budget-safe: calls are tagged loadtest=True so the shim serves a cached last-good
CoinGecko payload; high concurrency therefore does NOT multiply real upstream calls
(stays well within CoinGecko's 100/min, 10k/month Demo limits).
"""

from __future__ import annotations

import asyncio
import logging
import random

from .coingecko import get_watchlist
from .config import get_settings
from .metrics import metrics

logger = logging.getLogger(__name__)
settings = get_settings()


class LoadGenerator:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._users = 0
        self._rps_per_user = settings.load_default_rps_per_user
        self._stop_at: float | None = None

    @property
    def running(self) -> bool:
        return self._running

    def status(self) -> dict:
        return {
            "running": self._running,
            "users": self._users,
            "rps_per_user": self._rps_per_user,
            "target_rps": round(self._users * self._rps_per_user, 1),
            "simulated": True,
        }

    async def _user_loop(self) -> None:
        """One simulated user: refresh the watchlist forever at ~rps_per_user."""
        interval = 1.0 / self._rps_per_user if self._rps_per_user > 0 else 1.0
        while self._running:
            try:
                await get_watchlist(loadtest=True)
            except Exception:
                # Errors are already counted in metrics; keep the user alive.
                pass
            # Jitter so users don't thundering-herd in lockstep.
            await asyncio.sleep(interval * random.uniform(0.6, 1.4))

    async def start(self, users: int, rps_per_user: float, duration_s: int | None) -> dict:
        await self.stop()  # replace any existing run
        users = max(1, min(users, settings.load_max_users))
        rps_per_user = max(0.1, min(rps_per_user, 20.0))
        self._users = users
        self._rps_per_user = rps_per_user
        self._running = True
        metrics().set_simulated_users(users)
        self._tasks = [asyncio.create_task(self._user_loop()) for _ in range(users)]
        if duration_s and duration_s > 0:
            asyncio.create_task(self._auto_stop(duration_s))
        logger.info("loadgen started: %d users @ %.1f rps each", users, rps_per_user)
        return self.status()

    async def _auto_stop(self, duration_s: int) -> None:
        await asyncio.sleep(duration_s)
        await self.stop()

    async def stop(self) -> dict:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        self._users = 0
        metrics().set_simulated_users(0)
        return self.status()


_loadgen = LoadGenerator()


def loadgen() -> LoadGenerator:
    return _loadgen
