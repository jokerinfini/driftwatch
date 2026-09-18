from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _ensure_scheme(url: str) -> str:
    """Prepend https:// when a URL has no scheme.

    Render's Blueprint wires a service URL via ``fromService.property: host``, which yields
    a bare hostname (e.g. ``driftwatch-drift-shim.onrender.com``). httpx needs a scheme, so
    we normalise here. Localhost/explicit-scheme values are left untouched.
    """
    url = (url or "").strip()
    if not url or url.startswith(("http://", "https://")):
        return url
    return "https://" + url


class Settings(BaseSettings):
    """DriftWatch backend settings.

    DriftWatch is a live crypto watchlist + price-alerter whose real purpose is to
    showcase Mendr: every upstream (CoinGecko) call is a Mendr proxy envelope, and a
    controllable ``drift-shim`` upstream lets us flip the upstream response shape into
    a documented "drift" on demand so Mendr can heal it back to the declared contract.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "driftwatch"
    port: int = 8010
    log_level: str = "INFO"

    # --- Mendr egress (the gateway) --------------------------------------------
    # Every CoinGecko call is POSTed as a proxy envelope to the Mendr edge, which
    # resolves the upstream (our drift-shim), applies the approved heal, and validates
    # against the declared contract. Mendr sits ONLY on this egress, never on the
    # browser's read path.
    mendr_gateway_url: str = "http://localhost:8080"
    mendr_gateway_proxy_path: str = "/api/gateway/proxy"

    # real     -> POST the envelope to the real Mendr edge (production / pitch).
    # emulate  -> DEV ONLY: call the drift-shim directly and apply the SAME approved
    #             heal locally (from app/contract.py), so the full normal->drift->heal
    #             loop runs end-to-end without the real control/data plane. This does
    #             NOT reimplement a gateway service; it just lets us develop + test the
    #             contract + heal that we register in Mendr.
    mendr_mode: str = "emulate"

    # The controllable upstream that sits BEHIND Mendr. Used directly in emulate mode,
    # and always used to flip the drift switch (POST {drift_shim_url}/drift).
    drift_shim_url: str = "http://localhost:8090"

    http_timeout_seconds: float = 8.0

    # --- CoinGecko (the drift-prone upstream) ----------------------------------
    # Free Demo plan: 100 calls/min, 10k/month, no card. Attribution required.
    # The key only ever lives in this env and is forwarded via the envelope headers.
    coingecko_demo_key: str = ""
    coingecko_vs_currency: str = "inr"
    # Coins shown on the watchlist (CoinGecko ids), comma-separated.
    watchlist_ids: str = (
        "bitcoin,ethereum,solana,ripple,cardano,dogecoin,"
        "polkadot,chainlink,polygon-ecosystem-token,litecoin"
    )

    # --- Redis (metrics snapshot, price history, alerts, last-good contract cache) -
    redis_url: str = "redis://localhost:6379/0"
    # Last-good healthy payload TTL. The heal re-injects removed fields from the most
    # recent contract-valid payload, so this is how long a heal can "remember" values.
    last_good_ttl_s: int = 86400
    # Rolling price-history points kept per coin (for the alerter's baseline).
    history_max_points: int = 200

    # --- Price alerter ---------------------------------------------------------
    # Default alert when a coin moves more than this % vs its rolling average.
    alert_move_pct: float = 5.0
    alert_min_points: int = 3

    # --- CORS (the Vercel frontend origin) -------------------------------------
    cors_allow_origins: str = "http://localhost:3002,http://localhost:3000"

    # --- Load generator (SIMULATED traffic) ------------------------------------
    # Hard cap so a demo can't accidentally hammer the upstream; the shim caches
    # CoinGecko responses so high concurrency does not multiply real upstream calls.
    load_max_users: int = 500
    load_default_rps_per_user: float = 1.0
    # Rolling window (seconds) used to compute requests/min and p95 latency.
    metrics_window_s: int = 60

    # --- URL accessors (scheme-normalised for hosted deploys) ------------------
    def shim_base(self) -> str:
        return _ensure_scheme(self.drift_shim_url)

    def gateway_base(self) -> str:
        return _ensure_scheme(self.mendr_gateway_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
