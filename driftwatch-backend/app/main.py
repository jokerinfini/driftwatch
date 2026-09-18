"""DriftWatch backend - a live crypto watchlist + price-alerter that showcases Mendr.

Every upstream (CoinGecko) call is a Mendr proxy envelope. A controllable drift-shim
sits behind Mendr; flipping the drift switch makes the upstream return a documented
drifted shape, Mendr heals it back to the contract, and the app keeps working with zero
code change. A built-in SIMULATED load generator + live metrics let us honestly pitch
"hosted, load-tested to N simulated users".

The browser's read path is served by this backend from cache/Redis; Mendr is only ever
on the egress to CoinGecko.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from . import cache
from .coingecko import get_coin, get_watchlist, prewarm
from .config import get_settings
from .gateway_client import GatewayCallError, close_client, get_drift, set_drift
from .loadgen import loadgen
from .metrics import metrics
from .schemas import DriftRequest, LoadStartRequest

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [driftwatch] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s starting; mendr_mode=%s gateway=%s shim=%s",
        settings.service_name, settings.mendr_mode, settings.mendr_gateway_url, settings.drift_shim_url,
    )
    # Warm the last-good contract baseline in the background so heals work immediately.
    asyncio.create_task(prewarm())
    yield
    await loadgen().stop()
    await close_client()
    await cache.close_redis()


app = FastAPI(title="driftwatch-backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.service_name,
        "mendr_mode": settings.mendr_mode,
        "redis": "up" if await cache.ping() else "down",
    }


# --- Read path (served to the browser; Mendr is only on the egress below) ------


@app.get("/watchlist", tags=["watchlist"])
async def watchlist() -> dict:
    """Live watchlist: healed (with-Mendr) rows + the naive (no-Mendr) rows + meta."""
    try:
        return await get_watchlist()
    except GatewayCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/coin/{coin_id}", tags=["watchlist"])
async def coin(coin_id: str) -> dict:
    """One coin's 'project health' card (community/developer/trust) - the drift-rich view."""
    try:
        return await get_coin(coin_id)
    except GatewayCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/alerts", tags=["alerts"])
async def alerts(limit: int = Query(50, ge=1, le=200)) -> dict:
    return {"alerts": await cache.recent_alerts(limit)}


# --- Drift switch (proxies to the shim; works in any gateway mode) ------------


@app.get("/drift", tags=["drift"])
async def drift_status() -> dict:
    try:
        return await get_drift()
    except GatewayCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/drift", tags=["drift"])
async def drift_set(req: DriftRequest) -> dict:
    try:
        return await set_drift(req.scenario, req.enabled)
    except GatewayCallError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# --- Load generator (SIMULATED) ----------------------------------------------


@app.post("/load/start", tags=["load"])
async def load_start(req: LoadStartRequest) -> dict:
    return await loadgen().start(req.users, req.rps_per_user, req.duration_s)


@app.post("/load/stop", tags=["load"])
async def load_stop() -> dict:
    return await loadgen().stop()


@app.get("/load/status", tags=["load"])
async def load_status() -> dict:
    return loadgen().status()


# --- Metrics -----------------------------------------------------------------


@app.get("/metrics/snapshot", tags=["metrics"])
async def metrics_snapshot() -> dict:
    return {**metrics().snapshot(), "load": loadgen().status()}


@app.get("/metrics", tags=["metrics"])
async def metrics_stream():
    """Server-Sent Events stream of the live metrics snapshot (once per second)."""

    async def gen():
        while True:
            snap = {**metrics().snapshot(), "load": loadgen().status()}
            yield {"event": "metrics", "data": json.dumps(snap)}
            await asyncio.sleep(1.0)

    return EventSourceResponse(gen())
