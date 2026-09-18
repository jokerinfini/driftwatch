from __future__ import annotations

from pydantic import BaseModel, Field


class DriftRequest(BaseModel):
    # Drift scenario id understood by the shim (see driftwatch-drift-shim). "all" flips
    # every scenario at once for the big on-stage moment.
    scenario: str = "all"
    enabled: bool = True


class LoadStartRequest(BaseModel):
    users: int = Field(50, ge=1, le=5000, description="SIMULATED concurrent users")
    rps_per_user: float = Field(1.0, gt=0, le=20.0)
    duration_s: int | None = Field(None, ge=0, description="Auto-stop after N seconds")
