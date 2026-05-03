"""Lightning Radar Backend Application"""
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api import routes
from app.core.config import config
from app.core.database import Database
from app.services.blitzortung import BlitzortungClient
from app.services.cluster_tracker import ClusterManager
from app.services.connection_manager import ConnectionManager
from app.services.country_detector import CountryDetector

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===================== Lifespan Management =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    logger.info("Starting Lightning Radar Backend")

    # Initialize services
    app.db = Database(config.DB_PATH)

    # Apply persisted settings over defaults
    saved = app.db.load_settings()
    config.TARGET_NAME    = saved.get("target_name",     config.TARGET_NAME)
    config.TARGET_LAT       = float(saved.get("target_lat",      config.TARGET_LAT))
    config.TARGET_LON       = float(saved.get("target_lon",      config.TARGET_LON))
    config.ALERT_RADIUS_KM = float(saved.get("alert_radius_km", config.ALERT_RADIUS_KM))
    config.OBS_RADIUS_KM  = float(saved.get("obs_radius_km",   config.OBS_RADIUS_KM))
    logger.info(
        f"Loaded settings: target={config.TARGET_NAME} "
        f"({config.TARGET_LAT}, {config.TARGET_LON}), "
        f"alert_radius={config.ALERT_RADIUS_KM}km, "
        f"obs_radius={config.OBS_RADIUS_KM}km"
    )

    app.connection_manager = ConnectionManager()
    app.cluster_manager = ClusterManager(config.ALERT_RADIUS_KM)

    geojson_path = Path(config.DB_PATH).parent / "ne_110m_countries.geojson"
    app.country_detector = CountryDetector(str(geojson_path))

    app.blitz_client = BlitzortungClient(
        app.db,
        app.connection_manager,
        app.cluster_manager,
        country_detector=app.country_detector
    )

    # Set API routes dependencies
    routes.set_dependencies(app.db, app.connection_manager, app.blitz_client, app.cluster_manager)

    # Wire HDBSCAN broadcast callback — called after every re-cluster run
    async def _on_clusters_updated(clusters: list, removed_ids: list):
        for cid in removed_ids:
            await app.connection_manager.broadcast({"type": "cluster_removed", "id": cid})
        for cluster in clusters:
            await app.connection_manager.broadcast({"type": "cluster", **cluster})

    app.cluster_manager.set_broadcast_callback(_on_clusters_updated)

    # Start HDBSCAN loop and Blitzortung streaming
    await app.cluster_manager.start()
    blitz_task = asyncio.create_task(app.blitz_client.start())

    yield

    # Shutdown
    logger.info("Shutting down Lightning Radar Backend")
    app.blitz_client.stop()
    blitz_task.cancel()
    await app.cluster_manager.stop()

# ===================== FastAPI Application =====================
app = FastAPI(
    title="Lightning Radar API",
    description="Real-time lightning detection and analysis API",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(routes.router)

# Serve React frontend
@app.get("/")
async def root():
    """Serve the React frontend."""
    return FileResponse("index.html")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.WS_HOST,
        port=config.WS_PORT,
        log_level="info"
    )
