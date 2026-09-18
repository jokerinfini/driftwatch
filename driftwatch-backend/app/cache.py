"""Redis helpers: last-good contract cache, price history, and deal alerts.

Redis here is disposable (Render Key Value free is in-memory only), so nothing that
must survive a restart lives here. It holds:

- ``lastgood:{kind}:{id}`` - the most recent CONTRACT-VALID payload, so the heal can
  re-inject fields an upstream drift removed (e.g. community_data).
- ``history:{id}``          - a capped rolling list of prices, the alerter's baseline.
- ``alerts``               - a capped list of recent deal alerts (newest first).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from redis.asyncio import Redis

from .config import get_settings

settings = get_settings()

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Last-good contract cache (source of truth for heals) ---------------------


def _lastgood_key(kind: str, coin_id: str) -> str:
    return f"lastgood:{kind}:{coin_id}"


async def put_last_good(kind: str, coin_id: str, payload: dict) -> None:
    try:
        await get_redis().set(
            _lastgood_key(kind, coin_id),
            json.dumps(payload),
            ex=settings.last_good_ttl_s,
        )
    except Exception:
        # Never fail a request because the disposable cache is down.
        pass


async def get_last_good(kind: str, coin_id: str) -> dict | None:
    try:
        raw = await get_redis().get(_lastgood_key(kind, coin_id))
    except Exception:
        return None
    return json.loads(raw) if raw else None


# --- Price history + deal alerts ---------------------------------------------


def _history_key(coin_id: str) -> str:
    return f"history:{coin_id}"


ALERTS_KEY = "alerts"


async def record_price(coin_id: str, price: float) -> list[float]:
    """Append a price point (capped) and return the recent series."""
    redis = get_redis()
    key = _history_key(coin_id)
    try:
        await redis.rpush(key, price)
        await redis.ltrim(key, -settings.history_max_points, -1)
        raw = await redis.lrange(key, 0, -1)
    except Exception:
        return []
    return [float(x) for x in raw]


async def push_alert(alert: dict) -> None:
    try:
        redis = get_redis()
        alert = {**alert, "at": _now_iso()}
        await redis.lpush(ALERTS_KEY, json.dumps(alert))
        await redis.ltrim(ALERTS_KEY, 0, 199)
    except Exception:
        pass


async def recent_alerts(limit: int = 50) -> list[dict]:
    try:
        raw = await get_redis().lrange(ALERTS_KEY, 0, limit - 1)
    except Exception:
        return []
    return [json.loads(r) for r in raw]
