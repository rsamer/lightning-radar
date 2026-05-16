"""API routes for Lightning Radar."""
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..core.config import config
from ..models.schemas import HealthResponse, StatsResponse

logger = logging.getLogger(__name__)


class SettingsUpdate(BaseModel):
    target_name: Optional[str] = None
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None
    alert_radius_km: Optional[float] = None
    obs_radius_km: Optional[float] = None

# Router for REST endpoints
router = APIRouter()

# Global references (set by app)
_db = None
_connection_manager = None
_blitz_client = None
_cluster_manager = None


def set_dependencies(db, connection_manager, blitz_client, cluster_manager):
    """Set global dependencies for routes."""
    global _db, _connection_manager, _blitz_client, _cluster_manager
    _db = db
    _connection_manager = connection_manager
    _blitz_client = blitz_client
    _cluster_manager = cluster_manager


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(
        status="ok",
        connected_clients=_connection_manager.get_connected_count(),
        blitzortung_connected=_blitz_client.connected
    )


@router.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    """Get current statistics."""
    total_strikes = _db.get_total_strikes()
    strikes_last_hour = _db.get_strikes_last_hour()

    return StatsResponse(
        total_strikes=total_strikes,
        strikes_last_hour=strikes_last_hour,
        alert_radius_km=config.ALERT_RADIUS_KM,
        target={"name": config.TARGET_NAME, "lat": config.TARGET_LAT, "lon": config.TARGET_LON}
    )


@router.get("/api/settings")
async def get_settings():
    """Get current target location and alert settings."""
    return {
        "target_name": config.TARGET_NAME,
        "target_lat": config.TARGET_LAT,
        "target_lon": config.TARGET_LON,
        "alert_radius_km": config.ALERT_RADIUS_KM,
        "obs_radius_km": config.OBS_RADIUS_KM,
    }


@router.post("/api/settings")
async def update_settings(update: SettingsUpdate):
    """Update target location and alert settings at runtime."""
    if update.target_name is not None:
        config.TARGET_NAME = update.target_name
    if update.target_lat is not None:
        config.TARGET_LAT = update.target_lat
    if update.target_lon is not None:
        config.TARGET_LON = update.target_lon
    if update.alert_radius_km is not None:
        config.ALERT_RADIUS_KM = update.alert_radius_km
        _cluster_manager.alert_radius_km = update.alert_radius_km
    if update.obs_radius_km is not None:
        config.OBS_RADIUS_KM = update.obs_radius_km

    logger.info(
        f"Settings updated: target={config.TARGET_NAME} "
        f"({config.TARGET_LAT}, {config.TARGET_LON}), "
        f"alert_radius={config.ALERT_RADIUS_KM}km, "
        f"obs_radius={config.OBS_RADIUS_KM}km"
    )

    # Persist to database
    _db.save_settings({
        "target_name":     config.TARGET_NAME,
        "target_lat":      config.TARGET_LAT,
        "target_lon":      config.TARGET_LON,
        "alert_radius_km": config.ALERT_RADIUS_KM,
        "obs_radius_km":   config.OBS_RADIUS_KM,
    })

    # Notify all connected clients
    await _connection_manager.broadcast({
        "type":           "settings_updated",
        "target_name":    config.TARGET_NAME,
        "target_lat":     config.TARGET_LAT,
        "target_lon":     config.TARGET_LON,
        "alert_radius_km": config.ALERT_RADIUS_KM,
        "obs_radius_km":  config.OBS_RADIUS_KM,
    })

    return await get_settings()


@router.get("/api/clusters")
async def get_clusters():
    """Get all active clusters (diagnostic)."""
    clusters = await _cluster_manager.get_all_clusters()
    return {"count": len(clusters), "clusters": clusters}


@router.get("/api/debug/clusters")
async def debug_clusters():
    """Dump internal cluster state for debugging."""
    async with _cluster_manager.lock:
        result = []
        now = time.time()
        for cid, c in _cluster_manager.clusters.items():
            vel = c._velocity_wls()
            result.append({
                "id":               cid,
                "strikes":          c.strike_count,
                "centroid_hist_len": len(c._centroid_hist),
                "last_feed_ago_s":  round(now - c._last_feed, 1) if c._last_feed > 0 else None,
                "speed_kmh":        round(vel[2], 1) if vel is not None else None,
                "shape":            c._shape,
            })
        result.append({
            "strike_buf_total": len(_cluster_manager._strike_buf),
        })
        return sorted(result[:-1], key=lambda x: -x["strikes"]) + [result[-1]]


@router.get("/api/strikes")
async def get_recent_strikes(limit: int = 100):
    """Get recent strikes."""
    strikes = _db.get_recent_strikes(limit)
    return {"strikes": strikes}


@router.get("/api/strikes/history")
async def get_strikes_history(from_ms: int, to_ms: int, limit: int = 2000):
    """Get strikes within a time range for historical playback (up to -3h)."""
    strikes = _db.get_strikes_by_timerange(from_ms, to_ms, min(limit, 5000))
    return {"strikes": strikes, "from_ms": from_ms, "to_ms": to_ms}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time strike data."""
    await _connection_manager.connect(websocket)

    # Send rich init message with settings, recent strikes and active clusters
    total_strikes = _db.get_total_strikes()
    now_ms = int(time.time() * 1000)
    from_ms = now_ms - 30 * 60 * 1000          # last 30 minutes
    recent_strikes = _db.get_strikes_by_timerange(from_ms, now_ms, limit=5000)
    clusters = await _cluster_manager.get_all_clusters()

    await websocket.send_text(json.dumps({
        "type": "init",
        "total_strikes": total_strikes,
        "settings": {
            "target_name":    config.TARGET_NAME,
            "target_lat":     config.TARGET_LAT,
            "target_lon":     config.TARGET_LON,
            "alert_radius_km": config.ALERT_RADIUS_KM,
            "obs_radius_km":  config.OBS_RADIUS_KM,
        },
        "recent_strikes": recent_strikes,
        "clusters": clusters,
    }))

    try:
        while True:
            # Keep connection alive and receive messages
            data = await websocket.receive_text()
            logger.debug(f"Received from client: {data}")
    except WebSocketDisconnect:
        await _connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await _connection_manager.disconnect(websocket)
