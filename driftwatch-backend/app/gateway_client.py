"""Egress transport: every CoinGecko call goes out as a Mendr proxy envelope.

Two modes (see config.mendr_mode):

- ``real``    : POST the envelope to the real Mendr edge. Mendr resolves the route
                (our drift-shim), applies the approved heal, validates the contract,
                and returns the healthy shape. We read ``X-Mendr-*`` response headers
                (when present) to surface "drift caught / healed" in our metrics.
- ``emulate`` : DEV ONLY. Call the drift-shim directly (Mendr not required) and return
                the RAW (possibly drifted) payload; the caller applies the same approved
                heal from app/contract.py. Lets the whole normal->drift->heal loop run
                locally with no control/data plane.

This module is transport only. Contract validation + healing live in app/coingecko.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout_seconds),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class GatewayCallError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class FetchResult:
    raw: Any
    latency_ms: float
    mode: str
    mendr_healed: bool = False
    mendr_drift: bool = False
    headers: dict[str, str] = field(default_factory=dict)


def _gateway_url() -> str:
    return (
        settings.gateway_base().rstrip("/")
        + "/"
        + settings.mendr_gateway_proxy_path.lstrip("/")
    )


def build_envelope(endpoint: str, method: str, headers: dict[str, str]) -> dict:
    """The exact envelope Mendr expects (see the brief / OmniCart's gateway_client)."""
    return {
        "sourceService": settings.service_name,
        "targetService": "coingecko",
        "endpoint": endpoint,
        "method": method.upper(),
        "payload": {},
        "headers": headers,
    }


def _auth_headers(loadtest: bool) -> dict[str, str]:
    """Auth is forwarded to the upstream by Mendr; the key only lives in our env."""
    headers: dict[str, str] = {}
    if settings.coingecko_demo_key:
        headers["x-cg-demo-api-key"] = settings.coingecko_demo_key
    if loadtest:
        # Hint the shim it may serve a cached last-good payload (budget-safe fan-out).
        headers["x-driftwatch-loadtest"] = "1"
    return headers


async def fetch(endpoint: str, method: str = "GET", loadtest: bool = False) -> FetchResult:
    """Fetch an upstream endpoint through Mendr (real) or the shim (emulate)."""
    client = get_client()
    headers = _auth_headers(loadtest)
    start = time.perf_counter()

    try:
        if settings.mendr_mode == "real":
            envelope = build_envelope(endpoint, method, headers)
            resp = await client.post(_gateway_url(), json=envelope)
        else:  # emulate: call the shim directly
            url = settings.shim_base().rstrip("/") + endpoint
            resp = await client.request(method.upper(), url, headers=headers)
    except httpx.HTTPError as exc:
        raise GatewayCallError(f"gateway call failed: {exc}") from exc

    latency_ms = (time.perf_counter() - start) * 1000.0
    if resp.status_code >= 400:
        raise GatewayCallError(f"upstream HTTP {resp.status_code}", status_code=resp.status_code)

    try:
        raw = resp.json()
    except ValueError as exc:
        raise GatewayCallError(f"invalid JSON from upstream: {exc}") from exc

    hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return FetchResult(
        raw=raw,
        latency_ms=latency_ms,
        mode=settings.mendr_mode,
        mendr_healed=hdrs.get("x-mendr-healed", "").lower() in {"1", "true", "yes"},
        mendr_drift=hdrs.get("x-mendr-drift", "").lower() in {"1", "true", "yes"},
        headers=hdrs,
    )


async def set_drift(scenario: str, enabled: bool) -> dict:
    """Flip the drift switch on the shim (used regardless of gateway mode)."""
    url = settings.shim_base().rstrip("/") + "/drift"
    try:
        resp = await get_client().post(url, json={"scenario": scenario, "enabled": enabled})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise GatewayCallError(f"failed to set drift on shim: {exc}") from exc


async def get_drift() -> dict:
    url = settings.shim_base().rstrip("/") + "/drift"
    try:
        resp = await get_client().get(url)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise GatewayCallError(f"failed to read drift from shim: {exc}") from exc
