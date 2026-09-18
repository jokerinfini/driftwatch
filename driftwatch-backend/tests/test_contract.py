"""Contract validation + heal: each test mirrors a real, documented CoinGecko drift.

These prove the two halves of the Mendr value prop:
  1. drift detection - a drifted payload FAILS the declared contract, and
  2. heal            - the approved transform restores it so the app keeps working.
"""

from app import contract


def _healthy_market_row() -> dict:
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "image": "https://img/btc.png",
        "current_price": 5_600_000,
        "market_cap": 100_000_000_000,
        "market_cap_rank": 1,
        "price_change_percentage_24h": 1.5,
    }


def _healthy_coin() -> dict:
    return {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "market_data": {"current_price": {"inr": 5_600_000}},
        "community_data": {"reddit_subscribers": 6_000_000, "twitter_followers": 5_000_000},
        "developer_data": {"stars": 76_000, "forks": 36_000},
        "tickers": [{"trust_score": "green", "bid_ask_spread_percentage": 0.1}],
    }


# --- Healthy passes -----------------------------------------------------------


def test_healthy_market_row_passes():
    assert contract.validate_market_row(_healthy_market_row()) == []


def test_healthy_coin_passes():
    assert contract.validate_coin(_healthy_coin()) == []


# --- Markets drift: rehypothecation (2026-02-04) ------------------------------


def test_rehypothecation_drift_detected_and_healed():
    row = _healthy_market_row()
    row["market_cap_rank"] = None
    row["market_cap_rank_with_rehypothecated"] = 1
    assert "markets.market_cap_rank" in contract.validate_market_row(row)

    healed = contract.heal_market_row(row, last_good=None)
    assert contract.validate_market_row(healed) == []
    assert healed["market_cap_rank"] == 1


# --- Markets drift: renamed price field ---------------------------------------


def test_price_rename_drift_healed_via_transform():
    row = _healthy_market_row()
    row["price"] = row.pop("current_price")
    assert "markets.current_price" in contract.validate_market_row(row)

    healed = contract.heal_market_row(row, last_good=None)
    assert contract.validate_market_row(healed) == []
    assert healed["current_price"] == 5_600_000


# --- Markets drift: value removed (VEF currency deprecation) restored from last-good ---


def test_value_removed_healed_from_last_good():
    good = _healthy_market_row()
    row = _healthy_market_row()
    row["current_price"] = None
    assert "markets.current_price" in contract.validate_market_row(row)

    healed = contract.heal_market_row(row, last_good=good)
    assert contract.validate_market_row(healed) == []
    assert healed["current_price"] == good["current_price"]


# --- Coin drift: community_data + developer_data removed (2026-08-28) ----------


def test_community_developer_removed_detected_and_healed():
    coin = _healthy_coin()
    coin.pop("community_data")
    coin.pop("developer_data")
    problems = contract.validate_coin(coin)
    assert "coin.community_data" in problems
    assert "coin.developer_data" in problems

    healed = contract.heal_coin(coin, last_good=_healthy_coin())
    assert contract.validate_coin(healed) == []
    assert healed["community_data"]["reddit_subscribers"] == 6_000_000
    assert healed["developer_data"]["stars"] == 76_000


# --- Coin drift: twitter_followers removed (2025-05-15) -----------------------


def test_twitter_removed_detected_and_healed():
    coin = _healthy_coin()
    coin["community_data"].pop("twitter_followers")
    assert "coin.community_data.twitter_followers" in contract.validate_coin(coin)

    healed = contract.heal_coin(coin, last_good=_healthy_coin())
    assert contract.validate_coin(healed) == []
    assert healed["community_data"]["twitter_followers"] == 5_000_000


# --- Coin drift: trust_score null (2026-03-03) --------------------------------


def test_trust_score_null_detected_and_healed():
    coin = _healthy_coin()
    coin["tickers"][0]["trust_score"] = None
    assert "coin.tickers[0].trust_score" in contract.validate_coin(coin)

    # No last-good trust: heal derives from the (low) bid/ask spread -> green.
    healed = contract.heal_coin(coin, last_good=None)
    assert contract.validate_coin(healed) == []
    assert healed["tickers"][0]["trust_score"] == "green"


def test_bool_not_accepted_as_number():
    row = _healthy_market_row()
    row["current_price"] = True
    assert "markets.current_price" in contract.validate_market_row(row)
