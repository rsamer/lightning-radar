"""Blitzortung WebSocket client and data processor."""
import asyncio
import json
import logging
import time

import websockets

from ..core.config import config
from ..core.utils import decode_lzw, haversine

logger = logging.getLogger(__name__)


class BlitzortungClient:
    """Handle connection to Blitzortung and stream strike data."""

    def __init__(
        self,
        db,
        connection_manager,
        cluster_manager,
        country_detector=None,
    ):
        self.db = db
        self.connection_manager = connection_manager
        self.cluster_manager = cluster_manager
        self.country_detector = country_detector
        self.running = False
        self.connected = False

    async def start(self):
        """Start Blitzortung streaming with unlimited auto-reconnect."""
        self.running = True
        retry_count = 0

        while self.running:
            try:
                logger.info(f"Connecting to Blitzortung (attempt {retry_count + 1})...")
                await self._connect_and_stream()
                retry_count = 0
            except websockets.exceptions.WebSocketException as e:
                retry_count += 1
                wait_time = min(2 ** retry_count, 30)
                logger.error(f"Blitzortung connection error: {e}. Retrying in {wait_time}s...")
                self.connected = False
                await asyncio.sleep(wait_time)
            except Exception as e:
                retry_count += 1
                logger.error(f"Unexpected error: {e}. Retrying...")
                self.connected = False
                await asyncio.sleep(5)

    async def _connect_and_stream(self):
        async with websockets.connect(
            config.BLITZ_WS,
            ping_interval=30,
            ping_timeout=10
        ) as ws:
            self.connected = True
            logger.info("Connected to Blitzortung")
            await ws.send(json.dumps(config.BLITZ_INIT_MSG))
            async for raw_data in ws:
                await self._process_strike_data(raw_data)

    async def _process_strike_data(self, raw_data):
        try:
            decoded = decode_lzw(raw_data)
            data    = json.loads(decoded)

            lat = data.get("lat")
            lon = data.get("lon")
            if lat is None or lon is None:
                logger.debug(f"Skipping invalid strike data: {data}")
                return

            ts      = data.get("time", 0) // 1_000_000 or int(time.time() * 1000)
            country = self.country_detector.lookup(lat, lon) if self.country_detector else "??"

            self.db.add_strike(lat, lon, ts, "blitzortung", country)

            dist  = haversine(lat, lon, config.TARGET_LAT, config.TARGET_LON)
            total = self.db.get_total_strikes()

            await self.connection_manager.broadcast({
                "type":              "strike",
                "lat":               lat,
                "lon":               lon,
                "time_ms":           ts,
                "source":            "blitzortung",
                "country":           country,
                "db_total":          total,
                "dist_to_target_km": round(dist),
            })

            # Buffer strike for HDBSCAN — cluster updates are broadcast by ClusterManager
            await self.cluster_manager.add_strike(lat, lon, country)

        except json.JSONDecodeError:
            logger.warning(f"Failed to decode JSON: {str(raw_data)[:100]}")
        except Exception as e:
            logger.error(f"Error processing strike data: {e}", exc_info=True)

    def stop(self):
        self.running = False
        logger.info("Blitzortung client stopped")
