"""Tests for FastAPI API routes using TestClient."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import routes
from app.api.routes import router, set_dependencies
from app.core import config as config_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app(db=None, connection_manager=None, blitz_client=None, cluster_manager=None):
    """
    Build a minimal FastAPI app that includes the router but skips the full
    lifespan (no real DB, no real WebSocket, no Blitzortung connection).
    """
    if db is None:
        db = MagicMock()
        db.get_total_strikes = MagicMock(return_value=0)
        db.get_strikes_last_hour = MagicMock(return_value=0)
        db.get_recent_strikes = MagicMock(return_value=[])
        db.save_settings = MagicMock()

    if connection_manager is None:
        connection_manager = MagicMock()
        connection_manager.broadcast = AsyncMock()
        connection_manager.get_connected_count = MagicMock(return_value=0)

    if blitz_client is None:
        blitz_client = MagicMock()
        blitz_client.connected = False

    if cluster_manager is None:
        cluster_manager = MagicMock()
        cluster_manager.alert_radius_km = 50.0
        cluster_manager.get_all_clusters = AsyncMock(return_value=[])

    set_dependencies(db, connection_manager, blitz_client, cluster_manager)

    application = FastAPI()
    application.include_router(router)
    return application


@pytest.fixture(autouse=True)
def reset_config():
    """
    Reset config to defaults after every test so settings tests don't bleed.
    """
    cfg = config_module.config
    original = {
        "TARGET_NAME": cfg.TARGET_NAME,
        "TARGET_LAT": cfg.TARGET_LAT,
        "TARGET_LON": cfg.TARGET_LON,
        "ALERT_RADIUS_KM": cfg.ALERT_RADIUS_KM,
        "OBS_RADIUS_KM": cfg.OBS_RADIUS_KM,
    }
    yield
    cfg.TARGET_NAME = original["TARGET_NAME"]
    cfg.TARGET_LAT = original["TARGET_LAT"]
    cfg.TARGET_LON = original["TARGET_LON"]
    cfg.ALERT_RADIUS_KM = original["ALERT_RADIUS_KM"]
    cfg.OBS_RADIUS_KM = original["OBS_RADIUS_KM"]


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

def test_health_returns_200():
    """GET /health must return HTTP 200."""
    client = TestClient(make_app())
    resp = client.get("/health")
    assert resp.status_code == 200


def test_health_status_ok():
    """GET /health body must contain status='ok'."""
    client = TestClient(make_app())
    resp = client.get("/health")
    assert resp.json()["status"] == "ok"


def test_health_has_connected_clients():
    """GET /health body must include connected_clients key."""
    client = TestClient(make_app())
    resp = client.get("/health")
    assert "connected_clients" in resp.json()


def test_health_has_blitzortung_connected():
    """GET /health body must include blitzortung_connected key."""
    client = TestClient(make_app())
    resp = client.get("/health")
    assert "blitzortung_connected" in resp.json()


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

def test_stats_returns_200():
    """GET /api/stats must return HTTP 200."""
    db = MagicMock()
    db.get_total_strikes = MagicMock(return_value=42)
    db.get_strikes_last_hour = MagicMock(return_value=5)
    client = TestClient(make_app(db=db))
    resp = client.get("/api/stats")
    assert resp.status_code == 200


def test_stats_total_strikes():
    """GET /api/stats must return correct total_strikes."""
    db = MagicMock()
    db.get_total_strikes = MagicMock(return_value=42)
    db.get_strikes_last_hour = MagicMock(return_value=5)
    client = TestClient(make_app(db=db))
    body = client.get("/api/stats").json()
    assert body["total_strikes"] == 42


def test_stats_strikes_last_hour():
    """GET /api/stats must return correct strikes_last_hour."""
    db = MagicMock()
    db.get_total_strikes = MagicMock(return_value=0)
    db.get_strikes_last_hour = MagicMock(return_value=7)
    client = TestClient(make_app(db=db))
    body = client.get("/api/stats").json()
    assert body["strikes_last_hour"] == 7


def test_stats_alert_radius_km():
    """GET /api/stats must include alert_radius_km."""
    db = MagicMock()
    db.get_total_strikes = MagicMock(return_value=0)
    db.get_strikes_last_hour = MagicMock(return_value=0)
    client = TestClient(make_app(db=db))
    body = client.get("/api/stats").json()
    assert "alert_radius_km" in body


def test_stats_target_field():
    """GET /api/stats must include a 'target' dict with name, lat, lon."""
    db = MagicMock()
    db.get_total_strikes = MagicMock(return_value=0)
    db.get_strikes_last_hour = MagicMock(return_value=0)
    client = TestClient(make_app(db=db))
    body = client.get("/api/stats").json()
    assert "target" in body
    target = body["target"]
    assert "name" in target
    assert "lat" in target
    assert "lon" in target


# ---------------------------------------------------------------------------
# GET /api/settings
# ---------------------------------------------------------------------------

def test_get_settings_returns_200():
    """GET /api/settings must return HTTP 200."""
    client = TestClient(make_app())
    resp = client.get("/api/settings")
    assert resp.status_code == 200


def test_get_settings_has_required_keys():
    """GET /api/settings must return all required configuration keys."""
    client = TestClient(make_app())
    body = client.get("/api/settings").json()
    for key in ("target_name", "target_lat", "target_lon", "alert_radius_km", "obs_radius_km"):
        assert key in body, f"Missing key: {key}"


def test_get_settings_default_target_name():
    """GET /api/settings must return the default target_name 'Graz'."""
    # Reset config to known defaults first
    config_module.config.TARGET_NAME = "Vienna"
    client = TestClient(make_app())
    body = client.get("/api/settings").json()
    assert body["target_name"] == "Vienna"


# ---------------------------------------------------------------------------
# POST /api/settings
# ---------------------------------------------------------------------------

def test_post_settings_returns_200():
    """POST /api/settings must return HTTP 200."""
    db = MagicMock()
    db.save_settings = MagicMock()
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    client = TestClient(make_app(db=db, connection_manager=cm))
    resp = client.post("/api/settings", json={"target_name": "Vienna"})
    assert resp.status_code == 200


def test_post_settings_updates_target_name():
    """POST /api/settings must update config.TARGET_NAME."""
    db = MagicMock()
    db.save_settings = MagicMock()
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    client = TestClient(make_app(db=db, connection_manager=cm))

    client.post("/api/settings", json={
        "target_name": "Vienna",
        "target_lat": 48.21,
        "target_lon": 16.37,
    })

    assert config_module.config.TARGET_NAME == "Vienna"


def test_post_settings_response_contains_new_values():
    """POST /api/settings response must reflect the updated values."""
    db = MagicMock()
    db.save_settings = MagicMock()
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    client = TestClient(make_app(db=db, connection_manager=cm))

    resp = client.post("/api/settings", json={
        "target_name": "Vienna",
        "target_lat": 48.21,
        "target_lon": 16.37,
    })

    body = resp.json()
    assert body["target_name"] == "Vienna"
    assert body["target_lat"] == pytest.approx(48.21)
    assert body["target_lon"] == pytest.approx(16.37)


def test_post_settings_persists_to_db():
    """POST /api/settings must call db.save_settings."""
    db = MagicMock()
    db.save_settings = MagicMock()
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    client = TestClient(make_app(db=db, connection_manager=cm))

    client.post("/api/settings", json={"target_name": "Vienna"})

    db.save_settings.assert_called_once()


def test_post_settings_updates_alert_radius():
    """POST /api/settings with alert_radius_km must update config and cluster_manager."""
    db = MagicMock()
    db.save_settings = MagicMock()
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cluster_mgr = MagicMock()
    cluster_mgr.alert_radius_km = 50.0
    cluster_mgr.get_all_clusters = AsyncMock(return_value=[])

    client = TestClient(make_app(db=db, connection_manager=cm, cluster_manager=cluster_mgr))
    client.post("/api/settings", json={"alert_radius_km": 100.0})

    assert config_module.config.ALERT_RADIUS_KM == pytest.approx(100.0)
    assert cluster_mgr.alert_radius_km == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# GET /api/strikes
# ---------------------------------------------------------------------------

def test_get_strikes_returns_200():
    """GET /api/strikes must return HTTP 200."""
    db = MagicMock()
    db.get_recent_strikes = MagicMock(return_value=[])
    client = TestClient(make_app(db=db))
    resp = client.get("/api/strikes")
    assert resp.status_code == 200


def test_get_strikes_contains_strikes_key():
    """GET /api/strikes response must have a 'strikes' key."""
    db = MagicMock()
    db.get_recent_strikes = MagicMock(return_value=[])
    client = TestClient(make_app(db=db))
    body = client.get("/api/strikes").json()
    assert "strikes" in body
