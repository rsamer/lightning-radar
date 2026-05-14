"""WebSocket connection management."""
import asyncio
import json
import logging
from typing import Set

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Manage WebSocket connections to clients."""

    def __init__(self):
        self.active_connections: Set = set()
        self._broadcast_lock = asyncio.Lock()

    async def connect(self, websocket):
        """Accept and register a new connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    async def disconnect(self, websocket):
        """Remove a disconnected client."""
        self.active_connections.discard(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        Send message to all connected clients.

        Serialised by an asyncio.Lock to prevent concurrent iteration over the
        connection set while it is being modified.

        Args:
            message: Dictionary to be JSON serialized and sent
        """
        message_json = json.dumps(message)
        async with self._broadcast_lock:
            disconnected = set()

            for connection in self.active_connections:
                try:
                    await connection.send_text(message_json)
                except Exception as e:
                    logger.warning(f"Failed to send to client: {e}")
                    disconnected.add(connection)

            # Clean up disconnected clients
            for conn in disconnected:
                self.active_connections.discard(conn)

    def get_connected_count(self) -> int:
        """Get number of connected clients."""
        return len(self.active_connections)
