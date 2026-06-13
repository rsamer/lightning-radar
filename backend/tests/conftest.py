"""Shared fixtures for Lightning Radar test suite."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.core.database import Database


@pytest.fixture
def mem_db():
    """In-memory SQLite Database instance — isolated per test."""
    db = Database(":memory:")
    yield db
    db._conn.close()


@pytest.fixture
def mock_connection_manager():
    """Mock ConnectionManager with async broadcast."""
    mgr = MagicMock()
    mgr.broadcast = AsyncMock()
    mgr.get_connected_count = MagicMock(return_value=0)
    return mgr


@pytest.fixture
def mock_blitz_client():
    """Mock BlitzortungClient."""
    client = MagicMock()
    client.connected = True
    return client


@pytest.fixture
def mock_cluster_manager():
    """Mock ClusterManager with async methods."""
    mgr = MagicMock()
    mgr.update_cluster = AsyncMock(return_value=({"id": 0, "lat": 47.0, "lon": 15.0}, []))
    mgr.get_all_clusters = AsyncMock(return_value=[])
    return mgr
