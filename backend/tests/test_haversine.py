"""Tests for haversine distance function in app.core.utils."""
import pytest

from app.core.utils import haversine

# Known coordinates used as reference pairs
GRAZ_LAT,   GRAZ_LON   = 47.07, 15.44
VIENNA_LAT, VIENNA_LON = 48.21, 16.37


def test_same_point_distance_is_zero():
    """Distance from a point to itself must be exactly 0."""
    assert haversine(GRAZ_LAT, GRAZ_LON, GRAZ_LAT, GRAZ_LON) == 0.0


def test_graz_to_vienna_approximately_150km():
    """
    Graz to Vienna is approximately 150 km as the crow flies.
    Allow a generous band to accommodate coordinate rounding.
    """
    dist = haversine(GRAZ_LAT, GRAZ_LON, VIENNA_LAT, VIENNA_LON)
    assert 135.0 <= dist <= 165.0, f"Expected ~150 km, got {dist:.2f} km"


def test_symmetry():
    """haversine(a, b, c, d) must equal haversine(c, d, a, b)."""
    d1 = haversine(GRAZ_LAT, GRAZ_LON, VIENNA_LAT, VIENNA_LON)
    d2 = haversine(VIENNA_LAT, VIENNA_LON, GRAZ_LAT, GRAZ_LON)
    assert pytest.approx(d1, rel=1e-9) == d2


def test_returns_float():
    """Return type must always be float."""
    result = haversine(0.0, 0.0, 1.0, 1.0)
    assert isinstance(result, float)


def test_distance_positive_for_different_points():
    """Distance between two distinct points must be positive."""
    dist = haversine(0.0, 0.0, 0.0, 1.0)
    assert dist > 0
