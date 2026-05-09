"""Data models for Lightning Radar."""

from pydantic import BaseModel


class StatsResponse(BaseModel):
    """Statistics response model."""
    total_strikes: int
    strikes_last_hour: int
    alert_radius_km: float
    target: dict


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    connected_clients: int
    blitzortung_connected: bool
