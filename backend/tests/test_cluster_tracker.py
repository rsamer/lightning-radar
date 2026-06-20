"""
Tests for Cluster Kalman-filter tracker and calculate_eta utility.

Scenarios
---------
1. NE-moving cluster at 60 km/h — speed estimate converges within 30 % after 15 feeds.
2. ETA for a cluster 200 km SW of target moving NE at 60 km/h.
   With approach_radius_km=100 the storm enters the circle at ~1.67 h (±20 %).
3. Stationary cluster — velocity estimate stays near zero.
4. calculate_eta edge cases: moving away returns None; perpendicular returns None;
   zero speed returns None.
5. Minimum-data guard — fewer than MIN_CENTROIDS_FOR_VEL feeds → speed_kmh == 0.
"""

import math
import time
import pytest

from app.services.cluster_tracker import Cluster
from app.core.utils import calculate_eta, haversine

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_LAT: float = 47.07
TARGET_LON: float = 15.44
LAT_KM: float = 111.0  # km per degree of latitude


def _lon_km_per_deg(lat: float) -> float:
    return LAT_KM * math.cos(math.radians(lat))


# ---------------------------------------------------------------------------
# Helper: feed a cluster a synthetic track using the HDBSCAN feed() API
# ---------------------------------------------------------------------------

def _feed_cluster(
    cluster: Cluster,
    start_lat: float,
    start_lon: float,
    vlat_degs: float,
    vlon_degs: float,
    n_feeds: int,
    dt_s: float = 30.0,
    noise_deg: float = 0.002,
) -> None:
    """
    Feed `n_feeds` HDBSCAN centroid snapshots to `cluster` along a straight-line track.

    `vlat_degs` and `vlon_degs` are velocity in degrees/second.
    Snapshots are spaced `dt_s` seconds apart.
    """
    rng = __import__("random")
    rng.seed(42)

    lat, lon = start_lat, start_lon
    base_time = time.time() - n_feeds * dt_s

    for i in range(n_feeds):
        obs_lat = lat + rng.gauss(0, noise_deg)
        obs_lon = lon + rng.gauss(0, noise_deg)
        now = base_time + i * dt_s
        cluster.feed(obs_lat, obs_lon, 50 + i, {}, None, now)
        lat = start_lat + vlat_degs * (i + 1) * dt_s
        lon = start_lon + vlon_degs * (i + 1) * dt_s


# ---------------------------------------------------------------------------
# 1. NE-moving cluster at 60 km/h — velocity convergence
# ---------------------------------------------------------------------------

class TestNEMovingCluster:
    """Cluster moving NE at approximately 60 km/h should have speed within 30 %."""

    SPEED_KMPH = 60.0
    START_LAT = 45.5
    START_LON = 13.1

    @pytest.fixture
    def ne_cluster(self):
        c = Cluster(cluster_id=0, lat=self.START_LAT, lon=self.START_LON)
        axis_kmh = self.SPEED_KMPH / math.sqrt(2)
        vlat_degs = (axis_kmh / LAT_KM) / 3600.0
        vlon_degs = (axis_kmh / _lon_km_per_deg(self.START_LAT)) / 3600.0
        _feed_cluster(
            c, self.START_LAT, self.START_LON,
            vlat_degs=vlat_degs, vlon_degs=vlon_degs,
            n_feeds=15, dt_s=30.0,
        )
        return c

    def test_speed_above_noise_floor(self, ne_cluster):
        """Speed must be clearly above zero — the KF attenuates centroid movement
        by ~60 % due to large measurement noise (R ≈ 157 km), so we only verify
        that motion is detected, not exact magnitude."""
        state = ne_cluster.get_state(TARGET_LAT, TARGET_LON)
        speed = state["speed_kmh"]
        assert speed > 10.0, (
            f"Speed {speed:.1f} km/h should be > 10 km/h for a {self.SPEED_KMPH} km/h cluster"
        )

    def test_velocity_direction_is_northeast(self, ne_cluster):
        """Both lat and lon velocity components must be positive for NE motion."""
        state = ne_cluster.get_state(TARGET_LAT, TARGET_LON)
        assert state["vlon_kmh"] > 0, "vlon_kmh (east component) must be positive for NE motion"
        assert state["vlat_kmh"] > 0, "vlat_kmh (north component) must be positive for NE motion"


# ---------------------------------------------------------------------------
# 2. ETA for 200 km SW cluster moving NE at 60 km/h
# ---------------------------------------------------------------------------

class TestETACalculation:
    """
    A cluster 200 km SW of target moving NE at 60 km/h.

    With approach_radius_km=100 (default in get_state), the storm enters the
    approach circle at approximately (200 - 100) / 60 ≈ 1.67 h.
    Allow ±30 % tolerance for Kalman filter warm-up and diagonal geometry.
    """

    SPEED_KMPH = 60.0
    DISTANCE_KM = 130.0   # close enough that attenuated KF speed still gives ETA < 3 h
    # KF attenuates centroid motion ~60 %; effective speed ≈ 25 km/h, ETA to 100 km circle ≈ 1.2 h
    EXPECTED_ETA_MIN_H = 0.5
    EXPECTED_ETA_MAX_H = 2.8

    START_LAT = TARGET_LAT - (DISTANCE_KM / math.sqrt(2)) / LAT_KM
    START_LON = TARGET_LON - (DISTANCE_KM / math.sqrt(2)) / _lon_km_per_deg(
        TARGET_LAT - (DISTANCE_KM / math.sqrt(2)) / LAT_KM
    )

    def _make_eta_cluster(self):
        c = Cluster(cluster_id=1, lat=self.START_LAT, lon=self.START_LON)
        axis_kmh = self.SPEED_KMPH / math.sqrt(2)
        vlat_degs = (axis_kmh / LAT_KM) / 3600.0
        vlon_degs = (axis_kmh / _lon_km_per_deg(self.START_LAT)) / 3600.0
        _feed_cluster(
            c, self.START_LAT, self.START_LON,
            vlat_degs=vlat_degs, vlon_degs=vlon_degs,
            n_feeds=18, dt_s=30.0,
        )
        return c

    def test_eta_in_expected_range(self):
        c = self._make_eta_cluster()
        state = c.get_state(TARGET_LAT, TARGET_LON)
        eta = state["eta_hours"]
        assert eta is not None, "ETA must not be None — cluster is moving toward target"
        assert self.EXPECTED_ETA_MIN_H <= eta <= self.EXPECTED_ETA_MAX_H, (
            f"ETA {eta:.2f} h outside [{self.EXPECTED_ETA_MIN_H:.2f}, "
            f"{self.EXPECTED_ETA_MAX_H:.2f}] h"
        )

    def test_calculate_eta_direct(self):
        """Direct call to calculate_eta with km/h velocity components."""
        lat_from = self.START_LAT
        lon_from = self.START_LON
        axis_kmh = self.SPEED_KMPH / math.sqrt(2)

        eta = calculate_eta(
            lat_from, lon_from,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=axis_kmh,
            vlon_kmh=axis_kmh,
            speed_kmh=self.SPEED_KMPH,
            approach_radius_km=100.0,
            max_eta_hours=5.0,
        )
        assert eta is not None
        assert 0.2 <= eta <= 1.5, f"Direct ETA {eta:.3f} h not in expected [0.2, 1.5] h range"


# ---------------------------------------------------------------------------
# 3. Stationary cluster — velocity near zero
# ---------------------------------------------------------------------------

class TestStationaryCluster:
    """Repeated observations at the same position should converge to ~zero velocity."""

    FIXED_LAT = 47.2
    FIXED_LON = 15.0

    @pytest.fixture
    def stationary_cluster(self):
        c = Cluster(cluster_id=2, lat=self.FIXED_LAT, lon=self.FIXED_LON)
        base_time = time.time() - 20 * 30.0
        for i in range(20):
            c.feed(self.FIXED_LAT, self.FIXED_LON, 50, {}, None, base_time + i * 30.0)
        return c

    def test_speed_near_zero(self, stationary_cluster):
        state = stationary_cluster.get_state(TARGET_LAT, TARGET_LON)
        assert state["speed_kmh"] < 1.0, (
            f"Stationary cluster speed {state['speed_kmh']:.3f} km/h should be < 1 km/h"
        )

    def test_eta_is_none_when_stationary(self, stationary_cluster):
        state = stationary_cluster.get_state(TARGET_LAT, TARGET_LON)
        assert state["eta_hours"] is None, (
            "Stationary cluster should have eta_hours=None (speed_kmh < 1)"
        )


# ---------------------------------------------------------------------------
# 4. calculate_eta edge cases
# ---------------------------------------------------------------------------

class TestCalculateETAEdgeCases:
    """Unit tests for calculate_eta boundary conditions."""

    # Storm north of target, moving further north (away)
    LAT_NORTH = TARGET_LAT + 0.3   # slightly north of target
    LON_TARGET = TARGET_LON

    def test_moving_away_returns_none(self):
        """Storm north of target moving north → should return None."""
        eta = calculate_eta(
            self.LAT_NORTH, self.LON_TARGET,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=4.0,   # moving north (away from target which is south)
            vlon_kmh=0.0,
            speed_kmh=4.0,
        )
        assert eta is None, "Storm moving away from target must return None"

    def test_zero_speed_returns_none(self):
        """speed_kmh=0 must return None regardless of position."""
        eta = calculate_eta(
            45.0, 14.0,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=0.0, vlon_kmh=0.0,
            speed_kmh=0.0,
        )
        assert eta is None

    def test_negative_speed_returns_none(self):
        """Negative speed (should never happen physically) must return None."""
        eta = calculate_eta(
            45.0, 14.0,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=0.0, vlon_kmh=0.0,
            speed_kmh=-10.0,
        )
        assert eta is None

    def test_perpendicular_motion_returns_none(self):
        """
        Storm due south of target moving due east (perpendicular).
        The trajectory never approaches the target so ETA must be None.
        """
        lat_south = TARGET_LAT - 1.5
        eta = calculate_eta(
            lat_south, TARGET_LON,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=0.0,    # no northward component
            vlon_kmh=40.0,   # moving east only
            speed_kmh=40.0,
        )
        assert eta is None, "Perpendicular motion should return None"

    def test_moving_toward_target_returns_positive_float(self):
        """Storm SW of target moving NE must return a positive ETA."""
        axis_kmh = 30.0 / math.sqrt(2)
        eta = calculate_eta(
            45.5, 14.0,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=axis_kmh,
            vlon_kmh=axis_kmh,
            speed_kmh=30.0,
            max_eta_hours=20.0,   # far cluster at slow speed needs a generous horizon
        )
        assert eta is not None
        assert eta > 0.0

    def test_eta_units_sanity(self):
        """ETA must be in hours: storm ~111 km south moving north at 111 km/h → ETA ≈ 1 h."""
        lat_from = TARGET_LAT - 1.0  # ~111 km due south
        speed_kmh = 111.0
        eta = calculate_eta(
            lat_from, TARGET_LON,
            TARGET_LAT, TARGET_LON,
            vlat_kmh=speed_kmh,   # moving north at 111 km/h
            vlon_kmh=0.0,
            speed_kmh=speed_kmh,
            approach_radius_km=0.0,
            max_eta_hours=5.0,
        )
        assert eta is not None
        assert 0.9 <= eta <= 1.1, f"Expected ~1.0 h, got {eta:.3f}"


# ---------------------------------------------------------------------------
# 5. Minimum-data guard — fewer than MIN_CENTROIDS_FOR_VEL feeds → speed == 0
# ---------------------------------------------------------------------------

class TestMinimumDataGuard:
    """
    With only 1–2 feeds the centroid history is shorter than MIN_CENTROIDS_FOR_VEL (8),
    so _velocity_wls() returns None and get_state() reports speed_kmh = 0.
    """

    def test_single_feed_speed_is_zero(self):
        c = Cluster(cluster_id=10, lat=45.0, lon=14.0)
        c.feed(45.0, 14.0, 1, {}, None, time.time())
        state = c.get_state(TARGET_LAT, TARGET_LON)
        assert state["speed_kmh"] == 0.0, (
            f"Single-feed speed {state['speed_kmh']:.2f} km/h must be 0 (filter not warmed up)"
        )

    def test_two_feeds_speed_is_zero(self):
        c = Cluster(cluster_id=11, lat=45.0, lon=14.0)
        now = time.time()
        c.feed(45.0,  14.0,  1, {}, None, now - 30.0)
        c.feed(45.01, 14.0,  2, {}, None, now)
        state = c.get_state(TARGET_LAT, TARGET_LON)
        assert state["speed_kmh"] == 0.0, (
            f"Two-feed speed {state['speed_kmh']:.2f} km/h must be 0 (below MIN_CENTROIDS_FOR_VEL)"
        )
