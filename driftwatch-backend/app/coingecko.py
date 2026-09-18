"""CoinGecko orchestration: fetch through Mendr, validate the contract, heal, and
surface both the healthy ("with Mendr") and naive ("without Mendr") views so the UI can
show the live before/after. Also records the metric counters and drives the alerter.
"""

from __future__ import annotations

import asyncio
import logging

from . import cache, contract
from .config import get_settings
from .gateway_client import GatewayCallError, fetch
from .metrics import metrics

logger = logging.getLogger(__name__)
settings = get_settings()


def watchlist_ids() -> list[str]:
    return [c.strip() for c in settings.watchlist_ids.split(",") if c.strip()]


def _markets_endpoint() -> str:
    ids = ",".join(watchlist_ids())
    vs = settings.coingecko_vs_currency
    return (
        f"/api/v3/coins/markets?vs_currency={vs}&ids={ids}"
        "&order=market_cap_desc&per_page=50&page=1&price_change_percentage=24h"
    )


def _coin_endpoint(coin_id: str) -> str:
    return (
        f"/api/v3/coins/{coin_id}?localization=false&tickers=true&market_data=true"
        "&community_data=true&developer_data=true&sparkline=false"
    )


# --- Normalizers (contract shape -> compact view the UI renders) --------------


def normalize_market_row(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "symbol": (row.get("symbol") or "").upper(),
        "name": row.get("name"),
        "image": row.get("image"),
        "current_price": row.get("current_price"),
        "market_cap": row.get("market_cap"),
        "market_cap_rank": row.get("market_cap_rank"),
        "price_change_percentage_24h": row.get("price_change_percentage_24h"),
        "rehypothecated": row.get("market_cap_rank_with_rehypothecated") is not None,
    }


def normalize_coin(coin: dict) -> dict:
    md = coin.get("market_data") or {}
    community = coin.get("community_data") or {}
    developer = coin.get("developer_data") or {}
    tickers = coin.get("tickers") or []
    price = (md.get("current_price") or {}).get(contract.VS)
    trust = tickers[0].get("trust_score") if tickers and isinstance(tickers[0], dict) else None
    return {
        "id": coin.get("id"),
        "symbol": (coin.get("symbol") or "").upper(),
        "name": coin.get("name"),
        "price": price,
        "reddit_subscribers": community.get("reddit_subscribers"),
        "twitter_followers": community.get("twitter_followers"),
        "stars": developer.get("stars"),
        "forks": developer.get("forks"),
        "trust_score": trust,
    }


# --- Public API ---------------------------------------------------------------


async def get_watchlist(loadtest: bool = False) -> dict:
    """Return healed (with-Mendr) + naive (without-Mendr) watchlist views + meta."""
    try:
        result = await fetch(_markets_endpoint(), loadtest=loadtest)
    except GatewayCallError as exc:
        metrics().record_request(0.0, error=True)
        raise

    raw = result.raw if isinstance(result.raw, list) else []
    problems = contract.validate_markets(raw)

    # Gather last-good rows for the heal (only in emulate mode do we heal locally;
    # in real mode Mendr already healed, but we re-heal defensively - a no-op if clean).
    ids = [r.get("id") for r in raw if isinstance(r, dict)]
    last_good_by_id: dict[str, dict] = {}
    for cid in ids:
        lg = await cache.get_last_good("markets", cid)
        if lg:
            last_good_by_id[cid] = lg

    drift = bool(problems) or result.mendr_drift
    if problems:
        healed = contract.heal_markets(raw, last_good_by_id)
        healed_flag = True
    else:
        healed = raw
        healed_flag = result.mendr_healed

    metrics().record_request(
        result.latency_ms, error=False, healed=healed_flag, drift=drift
    )

    # Persist last-good for any row that is contract-valid after healing.
    for row in healed:
        if isinstance(row, dict) and not contract.validate_market_row(row):
            await cache.put_last_good("markets", row.get("id"), row)

    coins = [normalize_market_row(r) for r in healed if isinstance(r, dict)]
    naive = [normalize_market_row(r) for r in raw if isinstance(r, dict)]

    # Drive the alerter off the healthy prices.
    asyncio.create_task(_check_alerts(coins))

    return {
        "coins": coins,
        "naive": naive,
        "meta": {
            "mode": result.mode,
            "drift": drift,
            "healed": healed_flag,
            "problems": problems,
            "latency_ms": round(result.latency_ms, 1),
            "attribution": "Data by CoinGecko",
        },
    }


async def get_coin(coin_id: str) -> dict:
    try:
        result = await fetch(_coin_endpoint(coin_id), loadtest=False)
    except GatewayCallError:
        metrics().record_request(0.0, error=True)
        raise

    raw = result.raw if isinstance(result.raw, dict) else {}
    problems = contract.validate_coin(raw)
    last_good = await cache.get_last_good("coin", coin_id)

    drift = bool(problems) or result.mendr_drift
    if problems:
        healed = contract.heal_coin(raw, last_good)
        healed_flag = True
    else:
        healed = raw
        healed_flag = result.mendr_healed

    metrics().record_request(result.latency_ms, error=False, healed=healed_flag, drift=drift)

    if contract.validate_coin(healed):
        # Heal could not fully restore (e.g. drift flipped before any healthy baseline was
        # cached); keep serving what we have rather than failing the read.
        logger.warning("coin %s still non-contract after heal", coin_id)
    else:
        # Contract-valid: remember it as the last-good baseline for future heals.
        await cache.put_last_good("coin", coin_id, healed)

    return {
        "coin": normalize_coin(healed),
        "naive": normalize_coin(raw),
        "meta": {
            "mode": result.mode,
            "drift": drift,
            "healed": healed_flag,
            "problems": problems,
            "latency_ms": round(result.latency_ms, 1),
            "attribution": "Data by CoinGecko",
        },
    }


async def prewarm(featured: tuple[str, ...] = ("bitcoin",)) -> None:
    """Populate the last-good baseline on startup so a heal has values to restore even if
    the drift switch is flipped before the first healthy poll. Best-effort; ignores errors
    (e.g. the upstream is already drifted, or the shim/edge isn't reachable yet)."""
    try:
        await get_watchlist()
    except Exception as exc:  # noqa: BLE001 - startup convenience only
        logger.info("prewarm watchlist skipped: %s", exc)
    for cid in featured:
        try:
            await get_coin(cid)
        except Exception as exc:  # noqa: BLE001
            logger.info("prewarm coin %s skipped: %s", cid, exc)


async def _check_alerts(coins: list[dict]) -> None:
    """Record prices and flag coins moving more than the configured % vs baseline."""
    for coin in coins:
        cid, price = coin.get("id"), coin.get("current_price")
        if not cid or not isinstance(price, (int, float)):
            continue
        series = await cache.record_price(cid, float(price))
        if len(series) < settings.alert_min_points + 1:
            continue
        prior = series[:-1]
        baseline = sum(prior) / len(prior)
        if baseline <= 0:
            continue
        move_pct = (price - baseline) / baseline * 100.0
        if abs(move_pct) >= settings.alert_move_pct:
            await cache.push_alert(
                {
                    "coin": cid,
                    "symbol": coin.get("symbol"),
                    "price": price,
                    "baseline": round(baseline, 4),
                    "move_pct": round(move_pct, 2),
                    "direction": "up" if move_pct > 0 else "down",
                }
            )
