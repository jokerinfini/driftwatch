# DriftWatch - Decision Doc (Mendr pitch demo)

Status: Built. MVP runs end-to-end locally and is free-hostable.
Last updated: 2026-09-18

DriftWatch is a live crypto watchlist + price-alerter whose real purpose is to make
Mendr's value undeniable on stage: every upstream call is a Mendr proxy envelope, and a
controllable upstream lets us flip a real, documented CoinGecko schema break on demand so
Mendr heals it back to the contract live - the app never breaks.

---

## 1. Chosen idea (and why it beats the alternatives)

A crypto watchlist + per-coin "project health" card powered by **CoinGecko's free Demo
API**. Watchlist rows come from `/coins/markets`; the project-health card comes from
`/coins/{id}`. Both are routed through Mendr.

Why this beats the backups: CoinGecko's breaking changes are **frequent, documented with
exact dates, and land in fields a real UI renders** (rank column, 24h change, community/
developer stats, exchange trust). That makes the live "drift -> heal" moment concrete
rather than abstract. The free tier is also generous enough (100 calls/min, 10k/month, no
card) to run a load demo.

### Picked API: CoinGecko Demo (free) - verified 2026-09-18
- Limits: 10,000 call credits/month, 100 calls/min, no credit card, attribution required
  ("Data by CoinGecko"). Auth via `x-cg-demo-api-key` header (forwarded in the envelope).
  Sources: [pricing](https://www.coingecko.com/en/api/pricing),
  [status: 30->100 RPM May 2026](https://status.coingecko.com/info_notices).
- Drift evidence (all confirmed in the live changelog/status):
  - `twitter_followers` removed from `community_data` - effective **2025-05-15**.
    [status](https://status.coingecko.com/info_notices/290171)
  - ticker `trust_score` now returns `null` - effective **2026-03-03**.
    [changelog](https://docs.coingecko.com/changelog)
  - `community_data` + `developer_data` objects removed from `/coins/{id}` etc. - effective
    **2026-08-28** (stale until then).
    [status](https://status.coingecko.com/info_notices), [changelog](https://docs.coingecko.com/changelog)
  - Rehypothecated tokens: market-cap ranking changes + new GT/community flags appear in
    the current changelog (basis for our `market_cap_rank -> null` +
    `market_cap_rank_with_rehypothecated` scenario, ~2026-02-04).
- Honesty note: as of today these removals are **already live** on real CoinGecko, so a
  naive 2024-era client is genuinely broken right now - which is exactly what Mendr fixes.

### Backup APIs (evidence, why not primary)
- **OpenWeatherMap One Call**: 2.5 deprecated Jun 2024 -> 3.0 -> 4.0 recommended;
  `daily.summary` exists in 3.0 but is **removed in 4.0** (real schema break).
  [2.5 deprecation](https://openweathermap.org/one-call-1-deprecated),
  [3.0->4.0 migration](https://openweathermap.org/api/one-call-3-migration.md).
  Not primary: free tier (1,000/day) **requires a card**.
- **Alpha Vantage**: free tier cut to **25 req/day, 5/min**; quirky keys
  (`"Time Series (Daily)"`, `"1. open".."5. volume"`, all strings); on rate-limit returns
  `{"Note": ...}` instead of the series (behavior drift).
  [support](https://www.alphavantage.co/support/), [docs](https://www.alphavantage.co/documentation/).
  Not primary: 25/day is too low for a load demo.
- **Finnhub / Twelve Data**: Finnhub `/stock/candle` is premium -> **403 on free**, and
  NSE/BSE (`.NS`/`.BO`) 403 on free (US-only) - behavior drift.
  [issue #546](https://github.com/finnhubio/Finnhub-API/issues/546),
  [issue #513](https://github.com/finnhubio/Finnhub-API/issues/513).
  Twelve Data free = 8/min, 800/day, trial-symbol scope. Kept as an India/stock backup.

---

## 2. 60-second demo script
1. (0-10s) "DriftWatch - a live crypto watchlist. Every price comes from CoinGecko's free
   API, but never directly: every call is a Mendr proxy envelope." Show live INR prices
   ("Data by CoinGecko").
2. (10-20s) Metrics panel (labelled SIMULATED): run the load generator - "~200 simulated
   concurrent users, ~1,500 req/min, p95 ~40ms, 0 heals - all green. Hosted and load-tested."
3. (20-35s) "CoinGecko has a documented history of breaking its schema - community_data/
   developer_data removed Aug 28 2026, trust_score went null in March." Hit **Break
   everything**. The left "Without Mendr" watchlist + health card visibly break (missing
   rank, blank stats, trust null).
4. (35-50s) "Mendr caught the drift and healed it back to our contract - zero app code
   change." The right "With Mendr" view stays intact; "heals applied" + "drift caught"
   counters tick up.
5. (50-60s) Point at the Mendr dashboard: drift caught + healed live. "Our app never broke.
   That's Mendr."

---

## 3. Architecture

```
Browser (Vercel, React)
  -> driftwatch-backend (Render, FastAPI)   [read path: cache/Redis; SSE metrics]
       -> Mendr edge (the gateway)          [envelope; detects drift, heals, validates]
            -> driftwatch-drift-shim (Koyeb) [controllable upstream; /drift toggle]
                 -> real CoinGecko Demo API
  Redis (Render Key Value): metrics snapshot, price history, alerts, last-good contract
  Mendr control-plane dashboard: shows "drift caught + healed" (the money shot)
```

- **Gateway = real Mendr.** The app only POSTs the envelope; we do NOT build a gateway.
- **drift-shim is NOT a gateway** - it's the controllable upstream Mendr resolves to, so we
  can force drift on demand. `driftwatch-drift-shim/app/main.py`.
- **Emulate mode** (local dev): the backend calls the shim directly and applies the same
  approved heal from `driftwatch-backend/app/contract.py`, so the whole loop runs with no
  control/data plane. Production uses `MENDR_MODE=real`.
- **Load + metrics** are in-process; the shim caches CoinGecko so high concurrency stays
  within the free budget. All user/traffic numbers are SIMULATED and labelled as such.

---

## 4. Hosting (Option B - cold-start-safe, all free; personal GitHub `jokerinfini`)
- Frontend -> **Vercel Hobby** (`REACT_APP_API_BASE` = backend URL).
- Backend -> **Render free web service** (single service; keep-warm fits 750 hrs/mo).
- drift-shim -> **Koyeb free** (1-5s wake vs Render's ~1 min; must be public for Mendr).
- Redis -> **Render Key Value free** (25 MB, in-memory; our data is disposable).
- Mendr edge + control plane -> already deployed; `MENDR_GATEWAY_URL` points at it and the
  `coingecko` route points at the Koyeb shim.
- Keep-warm -> **cron-job.org** GET `/health` every 10 min during pitch week. Kafka skipped.

See [DRIFTWATCH_README.md](DRIFTWATCH_README.md) for run + deploy steps.
