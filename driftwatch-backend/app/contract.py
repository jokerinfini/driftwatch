"""The healthy CONTRACT, drift detection, and the approved HEAL.

This is the declarative "shape the client depends on" for each CoinGecko upstream, the
same shape declared in ``mendr-manifests/driftwatch.mendr.yaml``. In production the
Mendr control plane owns an approved heal that restores this contract; here we author
that transform once so:

  - ``emulate`` mode (local dev) applies it directly (no control/data plane needed), and
  - it doubles as a defensive re-heal + the source of the ``heals applied`` metric.

Two upstream kinds:
  - ``markets`` : a list of coins (CoinGecko /coins/markets) - the watchlist rows.
  - ``coin``    : one coin's "project health" detail (community/developer/trust).

Each drift below maps to a REAL, documented CoinGecko change (see DRIFTWATCH_DECISION.md):
  - market_cap_rank -> null + new market_cap_rank_with_rehypothecated (2026-02-04)
  - current_price renamed (generic "renamed field" drift, mirrors provider renames)
  - community_data / developer_data objects removed (2026-08-28)
  - community_data.twitter_followers removed (2025-05-15)
  - ticker trust_score -> null (2026-03-03)
"""

from __future__ import annotations

import copy
from typing import Any

VS = "inr"  # display currency the market_data price is keyed under

# Required (key, type) pairs for one /coins/markets row.
_MARKET_FIELDS: dict[str, tuple[type, ...]] = {
    "id": (str,),
    "symbol": (str,),
    "name": (str,),
    "image": (str,),
    "current_price": (int, float),
    "market_cap": (int, float),
    "market_cap_rank": (int,),
    "price_change_percentage_24h": (int, float),
}


def _is(value: Any, types: tuple[type, ...]) -> bool:
    # bool is a subclass of int; never accept it for numeric contract fields.
    if isinstance(value, bool):
        return bool in types
    return value is not None and isinstance(value, types)


# --- Validation ---------------------------------------------------------------


def validate_market_row(row: dict) -> list[str]:
    problems: list[str] = []
    for key, types in _MARKET_FIELDS.items():
        if not _is(row.get(key), types):
            problems.append(f"markets.{key}")
    return problems


def validate_markets(rows: Any) -> list[str]:
    if not isinstance(rows, list):
        return ["markets: not a list"]
    problems: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            problems.extend(f"{row.get('id', '?')}:{p}" for p in validate_market_row(row))
    return problems


def validate_coin(coin: Any) -> list[str]:
    if not isinstance(coin, dict):
        return ["coin: not an object"]
    problems: list[str] = []
    for key in ("id", "symbol", "name"):
        if not _is(coin.get(key), (str,)):
            problems.append(f"coin.{key}")

    md = coin.get("market_data")
    price = (md or {}).get("current_price", {}).get(VS) if isinstance(md, dict) else None
    if not _is(price, (int, float)):
        problems.append(f"coin.market_data.current_price.{VS}")

    community = coin.get("community_data")
    if not isinstance(community, dict):
        problems.append("coin.community_data")
    else:
        if not _is(community.get("reddit_subscribers"), (int,)):
            problems.append("coin.community_data.reddit_subscribers")
        if not _is(community.get("twitter_followers"), (int,)):
            problems.append("coin.community_data.twitter_followers")

    developer = coin.get("developer_data")
    if not isinstance(developer, dict):
        problems.append("coin.developer_data")
    else:
        if not _is(developer.get("stars"), (int,)):
            problems.append("coin.developer_data.stars")
        if not _is(developer.get("forks"), (int,)):
            problems.append("coin.developer_data.forks")

    tickers = coin.get("tickers")
    trust_ok = (
        isinstance(tickers, list)
        and tickers
        and isinstance(tickers[0], dict)
        and tickers[0].get("trust_score") in {"green", "yellow", "red"}
    )
    if not trust_ok:
        problems.append("coin.tickers[0].trust_score")

    return problems


# --- Heal ---------------------------------------------------------------------


def heal_market_row(row: dict, last_good: dict | None) -> dict:
    """Restore one drifted market row to the contract. Pure transforms first, then
    fall back to the last contract-valid values for anything still missing."""
    healed = dict(row)

    # Rehypothecation (2026-02-04): rank moved to a new field, old one nulled.
    if not _is(healed.get("market_cap_rank"), (int,)):
        rehyp = healed.get("market_cap_rank_with_rehypothecated")
        if _is(rehyp, (int,)):
            healed["market_cap_rank"] = rehyp

    # Generic renamed-field drift: price under an alternate key.
    if not _is(healed.get("current_price"), (int, float)):
        for alt in ("price", "current_price_inr", "sp"):
            if _is(healed.get(alt), (int, float)):
                healed["current_price"] = healed[alt]
                break
    if not _is(healed.get("price_change_percentage_24h"), (int, float)):
        for alt in ("price_change_24h", "change_24h_pct"):
            if _is(healed.get(alt), (int, float)):
                healed["price_change_percentage_24h"] = healed[alt]
                break

    # Anything still missing: re-inject the last contract-valid value.
    if last_good:
        for key, types in _MARKET_FIELDS.items():
            if not _is(healed.get(key), types) and _is(last_good.get(key), types):
                healed[key] = last_good[key]
    return healed


def heal_markets(rows: Any, last_good_by_id: dict[str, dict]) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [
        heal_market_row(row, last_good_by_id.get(row.get("id")))
        if isinstance(row, dict)
        else row
        for row in rows
    ]


def heal_coin(coin: dict, last_good: dict | None) -> dict:
    """Restore a drifted coin-detail to the contract by re-injecting the removed
    objects/fields from the last contract-valid payload (or safe structural defaults).

    Deep-copied so we never mutate the caller's raw payload (which stays the naive view)."""
    healed = copy.deepcopy(coin)
    lg = last_good or {}

    # market_data.current_price rename / restore
    md = healed.get("market_data")
    if not isinstance(md, dict):
        md = {}
    cp = md.get("current_price") if isinstance(md.get("current_price"), dict) else {}
    if not _is(cp.get(VS), (int, float)):
        lg_price = (lg.get("market_data", {}).get("current_price", {}) or {}).get(VS)
        # tolerate a renamed "price" scalar the shim may emit
        alt = md.get("price") if _is(md.get("price"), (int, float)) else None
        value = alt if alt is not None else lg_price
        if _is(value, (int, float)):
            cp = {**cp, VS: value}
    md = {**md, "current_price": cp}
    healed["market_data"] = md

    # community_data + twitter_followers (removed 2025-05-15 / 2026-08-28)
    community = healed.get("community_data")
    if not isinstance(community, dict):
        community = {}
    lg_comm = lg.get("community_data", {}) if isinstance(lg.get("community_data"), dict) else {}
    for key in ("reddit_subscribers", "twitter_followers"):
        if not _is(community.get(key), (int,)) and _is(lg_comm.get(key), (int,)):
            community[key] = lg_comm[key]
    healed["community_data"] = community

    # developer_data (removed 2026-08-28)
    developer = healed.get("developer_data")
    if not isinstance(developer, dict):
        developer = {}
    lg_dev = lg.get("developer_data", {}) if isinstance(lg.get("developer_data"), dict) else {}
    for key in ("stars", "forks"):
        if not _is(developer.get(key), (int,)) and _is(lg_dev.get(key), (int,)):
            developer[key] = lg_dev[key]
    healed["developer_data"] = developer

    # ticker trust_score -> null (2026-03-03): restore from last-good, else derive.
    tickers = healed.get("tickers")
    if not isinstance(tickers, list) or not tickers or not isinstance(tickers[0], dict):
        tickers = [dict((lg.get("tickers") or [{}])[0]) if lg.get("tickers") else {}]
    if tickers[0].get("trust_score") not in {"green", "yellow", "red"}:
        lg_trust = ((lg.get("tickers") or [{}])[0] or {}).get("trust_score")
        if lg_trust in {"green", "yellow", "red"}:
            tickers[0]["trust_score"] = lg_trust
        else:
            # Derive from bid/ask spread if present, else assume healthy.
            spread = tickers[0].get("bid_ask_spread_percentage")
            if isinstance(spread, (int, float)):
                tickers[0]["trust_score"] = "green" if spread < 0.5 else "yellow"
            else:
                tickers[0]["trust_score"] = "green"
    healed["tickers"] = tickers

    return healed
