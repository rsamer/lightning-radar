"""Core configuration for Lightning Radar backend."""
from dataclasses import dataclass, field


@dataclass
class Config:
    """Application configuration. Fields are mutable to allow runtime updates."""

    # WebSocket Server
    WS_HOST: str = "127.0.0.1"
    WS_PORT: int = 8765

    # Blitzortung
    BLITZ_WS: str = "wss://ws1.blitzortung.org"
    BLITZ_INIT_MSG: dict = field(default_factory=lambda: {"a": 111})

    # Target location (user-configurable at runtime)
    TARGET_NAME: str = "Graz"
    TARGET_LAT: float = 47.07
    TARGET_LON: float = 15.44

    # Radii
    OBS_RADIUS_KM: float = 500.0
    ALERT_RADIUS_KM: float = 50.0

    # Database (relative to the directory uvicorn is started from, i.e. backend/)
    DB_PATH: str = "data/lightning.db"


# Global config instance — mutate fields directly to update at runtime
config = Config()
