"""Tests for BlitzortungClient._process_strike_data."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.blitzortung import BlitzortungClient


def make_client(db=None, connection_manager=None, cluster_manager=None):
    """Helper: create a BlitzortungClient with mock dependencies."""
    if db is None:
        db = MagicMock()
        db.add_strike = MagicMock(return_value=True)

    if connection_manager is None:
        connection_manager = MagicMock()
        connection_manager.broadcast = AsyncMock()

    if cluster_manager is None:
        cluster_manager = MagicMock()
        cluster_manager.update_cluster = AsyncMock(
            return_value=({"id": 0, "lat": 47.15, "lon": 15.51}, [])
        )

    return BlitzortungClient(
        db=db,
        connection_manager=connection_manager,
        cluster_manager=cluster_manager,
    )


# ---------------------------------------------------------------------------
# Valid plain-JSON strike
# ---------------------------------------------------------------------------

async def test_valid_bytes_strike_calls_add_strike():
    """A valid plain-JSON bytes payload must call db.add_strike once."""
    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    payload = b'{"lat": 47.15, "lon": 15.51, "time": 1716001234567890000}'
    await cl._process_strike_data(payload)

    db.add_strike.assert_called_once()
    call_kwargs = db.add_strike.call_args
    args = call_kwargs[0]  # positional
    assert args[0] == pytest.approx(47.15)
    assert args[1] == pytest.approx(15.51)
    # Nanoseconds → milliseconds: 1716001234567890000 // 1_000_000 = 1716001234567
    assert args[2] == 1716001234567


async def test_valid_bytes_strike_calls_broadcast():
    """A valid plain-JSON payload must broadcast exactly one strike message."""
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(connection_manager=cm)

    payload = b'{"lat": 47.15, "lon": 15.51, "time": 1716001234567890000}'
    await cl._process_strike_data(payload)

    # broadcast may be called multiple times (strike + cluster), find the strike call
    strike_calls = [
        call for call in cm.broadcast.call_args_list
        if call[0][0].get("type") == "strike"
    ]
    assert len(strike_calls) == 1
    msg = strike_calls[0][0][0]
    assert msg["lat"] == pytest.approx(47.15)
    assert msg["lon"] == pytest.approx(15.51)
    assert msg["time_ms"] == 1716001234567
    assert msg["source"] == "blitzortung"


async def test_valid_str_strike_same_result_as_bytes():
    """str and bytes payloads with identical JSON must produce the same db call."""
    db_bytes = MagicMock()
    db_bytes.add_strike = MagicMock(return_value=True)
    cm_bytes = MagicMock()
    cm_bytes.broadcast = AsyncMock()

    db_str = MagicMock()
    db_str.add_strike = MagicMock(return_value=True)
    cm_str = MagicMock()
    cm_str.broadcast = AsyncMock()

    payload_bytes = b'{"lat": 1.0, "lon": 2.0}'
    payload_str = '{"lat": 1.0, "lon": 2.0}'

    cl_bytes = make_client(db=db_bytes, connection_manager=cm_bytes)
    cl_str = make_client(db=db_str, connection_manager=cm_str)

    await cl_bytes._process_strike_data(payload_bytes)
    await cl_str._process_strike_data(payload_str)

    assert db_bytes.add_strike.called
    assert db_str.add_strike.called

    args_bytes = db_bytes.add_strike.call_args[0]
    args_str = db_str.add_strike.call_args[0]

    assert args_bytes[0] == args_str[0]  # lat
    assert args_bytes[1] == args_str[1]  # lon


# ---------------------------------------------------------------------------
# Missing lat/lon
# ---------------------------------------------------------------------------

async def test_missing_lat_lon_does_not_call_add_strike():
    """A payload without lat/lon must not call db.add_strike."""
    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    await cl._process_strike_data(b'{"foo": "bar"}')

    db.add_strike.assert_not_called()


async def test_missing_lat_lon_does_not_broadcast():
    """A payload without lat/lon must not call connection_manager.broadcast."""
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(connection_manager=cm)

    await cl._process_strike_data(b'{"foo": "bar"}')

    cm.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# Garbage / invalid payload
# ---------------------------------------------------------------------------

async def test_garbage_payload_does_not_raise():
    """A completely garbage binary payload must not propagate any exception."""
    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    # This should not raise
    await cl._process_strike_data(b'\x00\x01\x02')


async def test_garbage_payload_does_not_call_db_or_broadcast():
    """A garbage payload must not trigger db.add_strike or broadcast."""
    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    await cl._process_strike_data(b'\x00\x01\x02')

    db.add_strike.assert_not_called()
    cm.broadcast.assert_not_called()


# ---------------------------------------------------------------------------
# Timestamp conversion
# ---------------------------------------------------------------------------

async def test_timestamp_nanoseconds_converted_to_milliseconds():
    """Blitzortung 'time' in nanoseconds must be stored and broadcast in milliseconds."""
    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    # 1,000,000,000 ns = 1,000 ms  (1 second)
    payload = b'{"lat": 10.0, "lon": 20.0, "time": 1000000000}'
    await cl._process_strike_data(payload)

    db.add_strike.assert_called_once()
    stored_time_ms = db.add_strike.call_args[0][2]
    assert stored_time_ms == 1000  # 1_000_000_000 // 1_000_000 = 1_000


async def test_missing_time_falls_back_to_current_time():
    """When 'time' is absent the stored time_ms must be a recent epoch millisecond value."""
    import time

    db = MagicMock()
    db.add_strike = MagicMock(return_value=True)
    cm = MagicMock()
    cm.broadcast = AsyncMock()
    cl = make_client(db=db, connection_manager=cm)

    before_ms = int(time.time() * 1000) - 100
    await cl._process_strike_data(b'{"lat": 10.0, "lon": 20.0}')
    after_ms = int(time.time() * 1000) + 100

    stored_time_ms = db.add_strike.call_args[0][2]
    assert before_ms <= stored_time_ms <= after_ms
