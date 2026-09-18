"""driftwatch-drift-shim - a controllable UPSTREAM that sits BEHIND Mendr.

This is NOT a gateway. In production, the real Mendr edge resolves the ``coingecko``
route to THIS service; Mendr does all the healing. The shim's only job is to give Mendr
something to heal on demand: it proxies real CoinGecko, and when the drift switch is
flipped it emits a DRIFTED response shape that mirrors a real, documented CoinGecko
breaking change.

Endpoints Mendr (or, in emulate mode, the backend) calls:
  - GET /api/v3/coins/markets   -> real CoinGecko markets (cached), + markets drift
  - GET /api/v3/coins/{id}      -> a coin "project health" detail built from the cached
                                   markets row + synthesized community/developer/tickers,
                                   + coin drift

Control endpoints (the drift switch):
  - GET  /drift                 -> current enabled scenarios
  - POST /drift {scenario,enabled}
  - GET  /health

Live prices/rank/24h-change are REAL (from CoinGecko). The community/developer/trust
fields are clearly-synthesized demo data, because CoinGecko already removed the real ones
(community_data/developer_data on 2026-08-28, trust_score null since 2026-03-03) - which is
exactly the drift Mendr exists to bridge. Healthy mode presents the pre-drift contract
shape; drift mode presents today's broken reality.
"""

from __future__ import annotations

import logging
import os
import time
import zlib
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [drift-shim] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="driftwatch-drift-shim")

COINGECKO_BASE = os.environ.get("COINGECKO_BASE", "https://api.coingecko.com")
SHIM_KEY = os.environ.get("COINGECKO_DEMO_KEY", "")
CACHE_TTL_S = float(os.environ.get("SHIM_CACHE_TTL_S", "45"))

# Each scenario maps to a real, documented CoinGecko change (see DRIFTWATCH_DECISION.md).
MARKET_SCENARIOS = {"rehypothecation", "rename_price", "vef_removed"}
COIN_SCENARIOS = {"community_removed", "twitter_removed", "trust_score_null"}
ALL_SCENARIOS = MARKET_SCENARIOS | COIN_SCENARIOS

# Enabled drift scenarios (the switch). Empty = healthy passthrough.
_enabled: set[str] = set()

# tiny in-memory cache: {ids_csv|vs: (ts, rows)} so load fan-out doesn't hammer CoinGecko.
_markets_cache: dict[str, tuple[float, list[dict]]] = {}


# --- Static fallback so the demo never hard-fails (offline / no key / rate limited) ---
_FALLBACK = {
    "bitcoin": ("btc", "Bitcoin", 5600000, 1),
    "ethereum": ("eth", "Ethereum", 300000, 2),
    "solana": ("sol", "Solana", 15000, 5),
    "ripple": ("xrp", "XRP", 210, 4),
    "cardano": ("ada", "Cardano", 55, 9),
    "dogecoin": ("doge", "Dogecoin", 18, 8),
    "polkadot": ("dot", "Polkadot", 600, 15),
    "chainlink": ("link", "Chainlink", 1500, 14),
    "polygon-ecosystem-token": ("pol", "Polygon", 40, 20),
    "litecoin": ("ltc", "Litecoin", 8500, 21),
}


def _fallback_rows(ids: list[str]) -> list[dict]:
    rows = []
    for cid in ids:
        sym, name, price, rank = _FALLBACK.get(cid, (cid[:3], cid.title(), 100, 99))
        rows.append(
            {
                "id": cid,
                "symbol": sym,
                "name": name,
                "image": f"https://assets.coingecko.com/coins/images/1/large/{cid}.png",
                "current_price": price,
                "market_cap": price * 19_000_000,
                "market_cap_rank": rank,
                "price_change_percentage_24h": 1.2,
            }
        )
    return rows


async def _fetch_markets(query: str, forward_key: str) -> list[dict]:
    """Fetch (and cache) real CoinGecko markets for the given raw query string."""
    params = parse_qs(query)
    ids = [c for c in (params.get("ids", [""])[0]).split(",") if c]
    vs = params.get("vs_currency", ["inr"])[0]
    cache_key = f"{','.join(ids)}|{vs}"

    hit = _markets_cache.get(cache_key)
    if hit and (time.time() - hit[0]) < CACHE_TTL_S:
        return hit[1]

    url = f"{COINGECKO_BASE}/api/v3/coins/markets?{query}"
    headers = {}
    key = forward_key or SHIM_KEY
    if key:
        headers["x-cg-demo-api-key"] = key
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code == 200 and isinstance(resp.json(), list):
            rows = resp.json()
        else:
            logger.warning("CoinGecko markets HTTP %s; using fallback", resp.status_code)
            rows = _fallback_rows(ids or list(_FALLBACK))
    except Exception as exc:
        logger.warning("CoinGecko markets failed (%s); using fallback", exc)
        rows = _fallback_rows(ids or list(_FALLBACK))

    _markets_cache[cache_key] = (time.time(), rows)
    return rows


def _stable(coin_id: str, salt: str, lo: int, hi: int) -> int:
    """Deterministic pseudo value from the coin id (stable synthesized demo data)."""
    h = zlib.crc32(f"{coin_id}:{salt}".encode()) & 0xFFFFFFFF
    return lo + (h % (hi - lo + 1))


# --- Drift shapers ------------------------------------------------------------


def _apply_market_drift(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        r = dict(row)
        if "rehypothecation" in _enabled:
            # 2026-02-04: rank moved to a new field; old field nulled.
            r["market_cap_rank_with_rehypothecated"] = r.get("market_cap_rank")
            r["market_cap_rank"] = None
        if "rename_price" in _enabled:
            # generic renamed-field drift: current_price -> price
            r["price"] = r.get("current_price")
            r.pop("current_price", None)
        if "vef_removed" in _enabled:
            # currency deprecation (VEF, 2026-06-30): the priced value goes missing.
            r["current_price"] = None
        out.append(r)
    return out


def _build_coin(coin_id: str, row: dict) -> dict:
    """Healthy pre-drift coin-detail contract shape (real price + synthesized health)."""
    price = row.get("current_price")
    if price is None:
        price = row.get("price")
    rank = row.get("market_cap_rank") or row.get("market_cap_rank_with_rehypothecated") or 50
    trust = "green" if rank <= 10 else ("yellow" if rank <= 30 else "red")
    return {
        "id": coin_id,
        "symbol": row.get("symbol", coin_id[:3]),
        "name": row.get("name", coin_id.title()),
        "market_data": {"current_price": {"inr": price}},
        "community_data": {
            "reddit_subscribers": _stable(coin_id, "reddit", 20_000, 6_000_000),
            "twitter_followers": _stable(coin_id, "twitter", 50_000, 9_000_000),
            "telegram_channel_user_count": _stable(coin_id, "tg", 1_000, 200_000),
        },
        "developer_data": {
            "stars": _stable(coin_id, "stars", 200, 80_000),
            "forks": _stable(coin_id, "forks", 50, 40_000),
            "subscribers": _stable(coin_id, "subs", 20, 4_000),
        },
        "tickers": [{"trust_score": trust, "bid_ask_spread_percentage": 0.12}],
    }


def _apply_coin_drift(coin: dict) -> dict:
    c = dict(coin)
    if "community_removed" in _enabled:
        # 2026-08-28: community_data + developer_data objects removed entirely.
        c.pop("community_data", None)
        c.pop("developer_data", None)
    elif "twitter_removed" in _enabled:
        # 2025-05-15: only twitter_followers removed from community_data.
        comm = dict(c.get("community_data") or {})
        comm.pop("twitter_followers", None)
        c["community_data"] = comm
    if "trust_score_null" in _enabled:
        # 2026-03-03: ticker trust_score now returns null.
        tickers = [dict(t) for t in (c.get("tickers") or [])]
        for t in tickers:
            t["trust_score"] = None
        c["tickers"] = tickers or [{"trust_score": None}]
    return c


# --- Routes -------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "driftwatch-drift-shim", "enabled": sorted(_enabled)}


@app.get("/drift")
def drift_status() -> dict:
    return {
        "enabled": sorted(_enabled),
        "scenarios": sorted(ALL_SCENARIOS),
        "drifted": bool(_enabled),
    }


@app.post("/drift")
async def drift_set(req: Request) -> dict:
    body = await req.json()
    scenario = str(body.get("scenario", "all"))
    enabled = bool(body.get("enabled", True))
    targets = ALL_SCENARIOS if scenario == "all" else {scenario} & ALL_SCENARIOS
    if not targets:
        return {"error": f"unknown scenario {scenario!r}", "scenarios": sorted(ALL_SCENARIOS)}
    if enabled:
        _enabled.update(targets)
    else:
        _enabled.difference_update(targets)
    logger.info("drift set scenario=%s enabled=%s -> %s", scenario, enabled, sorted(_enabled))
    return drift_status()


@app.get("/api/v3/coins/markets")
async def markets(request: Request) -> list[dict]:
    key = request.headers.get("x-cg-demo-api-key", "")
    rows = await _fetch_markets(request.url.query, key)
    return _apply_market_drift(rows)


@app.get("/api/v3/coins/{coin_id}")
async def coin(coin_id: str, request: Request) -> dict:
    key = request.headers.get("x-cg-demo-api-key", "")
    # Ensure we have a markets row for this coin (fetch just this id if needed).
    rows = await _fetch_markets(f"vs_currency=inr&ids={coin_id}", key)
    row = next((r for r in rows if r.get("id") == coin_id), None) or (
        _fallback_rows([coin_id])[0]
    )
    return _apply_coin_drift(_build_coin(coin_id, row))
