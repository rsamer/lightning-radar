"""Tests for app.core.database.Database."""
import time
import pytest

from app.core.database import Database


@pytest.fixture
def db():
    """Fresh in-memory Database per test."""
    instance = Database(":memory:")
    yield instance
    instance._conn.close()


# ---------------------------------------------------------------------------
# add_strike / get_recent_strikes
# ---------------------------------------------------------------------------

def test_add_strike_persists_row(db):
    """A strike added via add_strike must appear in get_recent_strikes."""
    db.add_strike(lat=47.15, lon=15.51, time_ms=1_716_000_000_000)
    strikes = db.get_recent_strikes()
    assert len(strikes) == 1
    assert strikes[0]["lat"] == pytest.approx(47.15)
    assert strikes[0]["lon"] == pytest.approx(15.51)
    assert strikes[0]["time_ms"] == 1_716_000_000_000


def test_add_strike_returns_true(db):
    """add_strike must return True on success."""
    result = db.add_strike(lat=1.0, lon=2.0, time_ms=123)
    assert result is True


def test_get_recent_strikes_empty_db(db):
    """get_recent_strikes on an empty DB must return an empty list."""
    assert db.get_recent_strikes() == []


def test_get_recent_strikes_limit(db):
    """get_recent_strikes must respect the limit parameter."""
    for i in range(10):
        db.add_strike(lat=float(i), lon=float(i), time_ms=i)
    strikes = db.get_recent_strikes(limit=3)
    assert len(strikes) == 3


def test_get_recent_strikes_ordered_descending(db):
    """get_recent_strikes must return rows newest-first."""
    db.add_strike(lat=1.0, lon=1.0, time_ms=1000)
    db.add_strike(lat=2.0, lon=2.0, time_ms=2000)
    db.add_strike(lat=3.0, lon=3.0, time_ms=3000)
    strikes = db.get_recent_strikes()
    assert strikes[0]["time_ms"] == 3000
    assert strikes[-1]["time_ms"] == 1000


# ---------------------------------------------------------------------------
# get_total_strikes
# ---------------------------------------------------------------------------

def test_get_total_strikes_empty_db(db):
    """get_total_strikes must return 0 on an empty database."""
    assert db.get_total_strikes() == 0


def test_get_total_strikes_after_one_insert(db):
    """get_total_strikes must return 1 after a single insert."""
    db.add_strike(lat=47.0, lon=15.0, time_ms=1000)
    assert db.get_total_strikes() == 1


def test_get_total_strikes_counts_all(db):
    """get_total_strikes must count every row."""
    for i in range(5):
        db.add_strike(lat=float(i), lon=float(i), time_ms=i)
    assert db.get_total_strikes() == 5


# ---------------------------------------------------------------------------
# get_strikes_last_hour
# ---------------------------------------------------------------------------

def test_get_strikes_last_hour_empty_db(db):
    """get_strikes_last_hour returns 0 on an empty database."""
    assert db.get_strikes_last_hour() == 0


def test_recent_strike_counted_in_last_hour(db):
    """A strike with a current timestamp must be counted in the last-hour total."""
    now_ms = int(time.time() * 1000)
    db.add_strike(lat=47.0, lon=15.0, time_ms=now_ms)
    assert db.get_strikes_last_hour() == 1


def test_old_strike_not_counted_in_last_hour(db):
    """A strike with time_ms=0 (ancient) must NOT be counted in the last-hour total."""
    db.add_strike(lat=47.0, lon=15.0, time_ms=0)
    assert db.get_strikes_last_hour() == 0


def test_mixed_strikes_last_hour_count(db):
    """Only the recent strike must be counted, not the old one."""
    now_ms = int(time.time() * 1000)
    db.add_strike(lat=47.0, lon=15.0, time_ms=now_ms)  # recent
    db.add_strike(lat=48.0, lon=16.0, time_ms=0)       # ancient
    assert db.get_strikes_last_hour() == 1


# ---------------------------------------------------------------------------
# Settings persistence (load_settings / save_settings)
# ---------------------------------------------------------------------------

def test_load_settings_returns_defaults(db):
    """load_settings must return the seeded default values."""
    settings = db.load_settings()
    assert "target_name" in settings
    assert settings["target_name"] == "Vienna"
    assert settings["target_lat"] == pytest.approx(48.21)
    assert settings["target_lon"] == pytest.approx(16.37)


def test_save_and_load_settings_round_trip(db):
    """Values saved via save_settings must be returned unchanged by load_settings."""
    db.save_settings({
        "target_name": "Vienna",
        "target_lat": 48.21,
        "target_lon": 16.37,
        "alert_radius_km": 75.0,
        "obs_radius_km": 500.0,
    })
    settings = db.load_settings()
    assert settings["target_name"] == "Vienna"
    assert settings["target_lat"] == pytest.approx(48.21)
    assert settings["target_lon"] == pytest.approx(16.37)
    assert settings["alert_radius_km"] == pytest.approx(75.0)
    assert settings["obs_radius_km"] == pytest.approx(500.0)


def test_save_settings_partial_update(db):
    """save_settings must update only the supplied keys."""
    db.save_settings({"target_name": "Linz"})
    settings = db.load_settings()
    assert settings["target_name"] == "Linz"
    # Other keys must retain their default seeded values
    assert settings["target_lat"] == pytest.approx(48.21)


def test_numeric_settings_loaded_as_float(db):
    """Numeric setting keys must be returned as float, not str."""
    settings = db.load_settings()
    assert isinstance(settings["target_lat"], float)
    assert isinstance(settings["alert_radius_km"], float)


def test_target_name_loaded_as_str(db):
    """target_name must be returned as a str (not cast to float)."""
    settings = db.load_settings()
    assert isinstance(settings["target_name"], str)
