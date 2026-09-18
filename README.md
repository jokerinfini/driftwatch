# DriftWatch

A live crypto watchlist + price-alerter that **stays up when CoinGecko changes its
schema**. Built to showcase **Mendr**, a schema-drift healing gateway. See
[DECISION.md](DECISION.md) for the why, the CoinGecko drift evidence, and the 60-second
demo script.

> Deployed **without Mendr yet** (`MENDR_MODE=emulate`): the backend calls the drift-shim
> directly and applies the same approved heal locally, so the full **normal → drift → heal**
> loop works live today. Wiring the real Mendr edge is a one-line switch (see below).

## Components
- `driftwatch-backend/` — FastAPI: watchlist + coin health via the Mendr envelope, contract
  validation + heal, price-alerter, SIMULATED load generator, live metrics (SSE).
- `driftwatch-drift-shim/` — a controllable CoinGecko upstream that sits **behind** Mendr;
  `/drift` flips real, documented CoinGecko breaks on demand. (Not a gateway.)
- `driftwatch-frontend/` — React: before/after (with/without Mendr) watchlist + health card,
  the drift switch, the load panel, and the live SIMULATED metrics panel.
- `mendr-manifests/driftwatch.mendr.yaml` — the healthy CoinGecko contract (drift/heal target).

## Run locally

```bash
docker compose up --build     # then open http://localhost:3002
```

Flip drift from the UI (**Break everything**) or:

```bash
curl -X POST localhost:8010/drift -H 'content-type: application/json' -d '{"scenario":"all","enabled":true}'
```

Backend tests: `cd driftwatch-backend && python -m pytest -q`

## Deploy (all free)

### 1. Backend + drift-shim + Redis → Render (Blueprint)
Render Dashboard → **New → Blueprint** → pick this repo. It reads [`render.yaml`](render.yaml)
and creates `driftwatch-backend`, `driftwatch-drift-shim`, and `driftwatch-redis` (Redis is
auto-wired). Then in the dashboard:
1. Open `driftwatch-drift-shim` and copy its URL (e.g. `https://driftwatch-drift-shim.onrender.com`).
2. On `driftwatch-backend` → Environment, set `DRIFT_SHIM_URL` to that URL, and
   `CORS_ALLOW_ORIGINS` to your Vercel origin. Save (redeploys). `COINGECKO_DEMO_KEY` optional
   on both services.

### 2. Frontend → Vercel
Import this repo, **Root Directory = `driftwatch-frontend`**. Set build env
`REACT_APP_API_BASE = https://driftwatch-backend.onrender.com` (your backend URL). Deploy,
then copy the Vercel URL back into the backend's `CORS_ALLOW_ORIGINS`.

### 3. Keep-warm (so nothing cold-starts on stage)
cron-job.org → GET `https://<backend>/health` and `https://<shim>/health` every 10 min.

## Wire the real Mendr edge (tonight)
1. Register `mendr-manifests/driftwatch.mendr.yaml` in the Mendr control plane; add the
   approved heal (mirrors `driftwatch-backend/app/contract.py`); route `coingecko` → the
   deployed shim URL.
2. On `driftwatch-backend` set `MENDR_MODE=real` and `MENDR_GATEWAY_URL=https://<mendr-edge>`.
   Every call now flows through the real edge and heals show on the Mendr dashboard.

## Honesty
All traffic/user figures are **SIMULATED** by the built-in load generator and labelled as
such in the UI — never a claim of real users. Live prices are real CoinGecko data
("Data by CoinGecko"); the community/developer/trust fields in the shim are clearly
synthesized demo data (CoinGecko already removed the real ones — the very drift Mendr bridges).
