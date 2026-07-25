"""Tests for haversine distance function in app.core.utils."""
import pytest

from app.core.utils import haversine

# Known coordinates used as reference pairs
VIENNA_LAT,   VIENNA_LON   = 48.21, 16.37
SALZBURG_LAT, SALZBURG_LON = 47.80, 13.04


def test_same_point_distance_is_zero():
    """Distance from a point to itself must be exactly 0."""
    assert haversine(VIENNA_LAT, VIENNA_LON, VIENNA_LAT, VIENNA_LON) == 0.0


def test_vienna_to_salzburg_approximately_250km():
    """
    Vienna → Salzburg is approximately 250 km as the crow flies (haversine with R=6371).
    Allow a ±5 km band to accommodate minor coordinate variation.
    """
    dist = haversine(VIENNA_LAT, VIENNA_LON, SALZBURG_LAT, SALZBURG_LON)
    assert 245.0 <= dist <= 255.0, f"Expected ~250 km, got {dist:.2f} km"


def test_symmetry():
    """haversine(a, b, c, d) must equal haversine(c, d, a, b)."""
    d1 = haversine(VIENNA_LAT, VIENNA_LON, SALZBURG_LAT, SALZBURG_LON)
    d2 = haversine(SALZBURG_LAT, SALZBURG_LON, VIENNA_LAT, VIENNA_LON)
    assert pytest.approx(d1, rel=1e-9) == d2


def test_returns_float():
    """Return type must always be float."""
    result = haversine(0.0, 0.0, 1.0, 1.0)
    assert isinstance(result, float)


def test_distance_positive_for_different_points():
    """Distance between two distinct points must be positive."""
    dist = haversine(0.0, 0.0, 0.0, 1.0)
    assert dist > 0
