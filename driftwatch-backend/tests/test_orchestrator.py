"""End-to-end (in-process) orchestrator tests: fetch -> validate -> heal -> metrics,
with the gateway transport mocked so no network/Mendr is required.
"""

import asyncio

import pytest

from app import coingecko
from app.gateway_client import FetchResult


def _drifted_markets():
    return [
        {
            "id": "bitcoin",
            "symbol": "btc",
            "name": "Bitcoin",
            "image": "https://img/btc.png",
            # rehypothecation drift: rank moved to new field, old one nulled
            "market_cap_rank": None,
            "market_cap_rank_with_rehypothecated": 1,
            "market_cap": 100_000_000_000,
            "current_price": 5_600_000,
            "price_change_percentage_24h": 1.5,
        }
    ]


def _drifted_coin():
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_data": {"current_price": {"inr": 5_600_000}},
        # community_data + developer_data removed (2026-08-28)
        "tickers": [{"trust_score": None, "bid_ask_spread_percentage": 0.1}],
    }


async def test_get_watchlist_heals_and_reports(monkeypatch):
    async def fake_fetch(endpoint, method="GET", loadtest=False):
        return FetchResult(raw=_drifted_markets(), latency_ms=5.0, mode="emulate")

    monkeypatch.setattr(coingecko, "fetch", fake_fetch)
    res = await coingecko.get_watchlist()

    assert res["meta"]["drift"] is True
    assert res["meta"]["healed"] is True
    # healed (with-Mendr) view restores the rank; naive (no-Mendr) view is broken.
    assert res["coins"][0]["market_cap_rank"] == 1
    assert res["coins"][0]["rehypothecated"] is True
    assert res["naive"][0]["market_cap_rank"] is None
    await asyncio.sleep(0)  # let the fire-and-forget alerts task settle


async def test_get_coin_heals_missing_objects(monkeypatch):
    # Seed last-good so the heal can re-inject the removed community/developer objects.
    from app import cache

    await cache.put_last_good(
        "coin",
        "bitcoin",
        {
            "id": "bitcoin",
            "symbol": "btc",
            "name": "Bitcoin",
            "market_data": {"current_price": {"inr": 5_600_000}},
            "community_data": {"reddit_subscribers": 6_000_000, "twitter_followers": 5_000_000},
            "developer_data": {"stars": 76_000, "forks": 36_000},
            "tickers": [{"trust_score": "green"}],
        },
    )

    async def fake_fetch(endpoint, method="GET", loadtest=False):
        return FetchResult(raw=_drifted_coin(), latency_ms=7.0, mode="emulate")

    monkeypatch.setattr(coingecko, "fetch", fake_fetch)
    res = await coingecko.get_coin("bitcoin")

    assert res["meta"]["healed"] is True
    assert res["coin"]["reddit_subscribers"] == 6_000_000
    assert res["coin"]["stars"] == 76_000
    assert res["coin"]["trust_score"] == "green"
    # naive view shows the drift (missing community + null trust)
    assert res["naive"]["reddit_subscribers"] is None
    assert res["naive"]["trust_score"] is None


async def test_get_watchlist_clean_passthrough(monkeypatch):
    healthy = _drifted_markets()[0]
    healthy["market_cap_rank"] = 1
    healthy.pop("market_cap_rank_with_rehypothecated")

    async def fake_fetch(endpoint, method="GET", loadtest=False):
        return FetchResult(raw=[healthy], latency_ms=3.0, mode="real", mendr_healed=False)

    monkeypatch.setattr(coingecko, "fetch", fake_fetch)
    res = await coingecko.get_watchlist()
    assert res["meta"]["drift"] is False
    assert res["meta"]["healed"] is False
    assert res["coins"][0]["market_cap_rank"] == 1
    await asyncio.sleep(0)
