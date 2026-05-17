"""Utility functions for Lightning Radar."""
import logging
import math

logger = logging.getLogger(__name__)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.
    Returns distance in kilometers.
    """
    R = 6371.0  # Earth radius in km
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = math.sin(d_lat/2)**2 + math.cos(math.radians(lat1)) * \
        math.cos(math.radians(lat2)) * math.sin(d_lon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def decode_lzw(data) -> str:
    """
    Decode Blitzortung's LZW-compressed data.

    Blitzortung sends WebSocket frames that are either:
    - Plain JSON text (newer protocol)
    - LZW-compressed strings where each character's ordinal is an LZW code point

    For binary frames, latin-1 decoding is required (1:1 byte→char mapping);
    UTF-8 would silently corrupt byte values > 127 via the replacement character.
    """
    if isinstance(data, bytes):
        data = data.decode('latin-1')

    if len(data) == 0:
        return '{}'

    # No fast-path: the LZW decoder is an identity on pure ASCII, so plain-JSON
    # frames decode correctly without any special case. A char-based fast-path
    # would short-circuit on Blitzortung LZW frames (which start with '{') and
    # return the raw compressed bytes, causing json.loads to fail on code-points > 255.

    e = {}
    d = list(data)
    c = d[0]
    f = c
    g = [c]
    h = 256
    o = h

    for i in range(1, len(d)):
        try:
            a = ord(d[i])
            if a < h:
                a = d[i]
            elif a in e:
                a = e[a]
            else:
                a = f + c
            g.append(a)
            c = a[0]
            e[o] = f + c
            o += 1
            f = a
        except (IndexError, KeyError, TypeError) as ex:
            logger.warning(f"LZW decode error at index {i}: {ex}")
            continue

    return ''.join(g)


def calculate_eta(
    lat_from: float,
    lon_from: float,
    lat_to: float,
    lon_to: float,
    vlat_kmh: float,
    vlon_kmh: float,
    speed_kmh: float,
    approach_radius_km: float = 100.0,
    max_eta_hours: float = 3.0,
) -> float | None:
    """
    Return hours until the cluster enters the approach_radius_km circle around
    the target, using ray-circle intersection (quadratic formula).

    Returns None when:
    - Speed is effectively zero
    - The trajectory misses the approach circle entirely (discriminant < 0)
    - The intersection only occurs in the past
    - ETA exceeds max_eta_hours

    Cluster position at time t (h): (lon + vlon*t, lat + vlat*t)
    Circle intersection: vel_sq·t² − 2·dot_dv·t + (dist_sq − r²) = 0
    where dot_dv = dx·vlon + dy·vlat (eastward/northward components matched)
    """
    if speed_kmh < 1.0:
        return None

    LAT_KM = 111.0
    lon_km = LAT_KM * math.cos(math.radians(lat_from))

    dx_km = (lon_to - lon_from) * lon_km   # eastward km to target
    dy_km = (lat_to - lat_from) * LAT_KM   # northward km to target

    vel_sq  = vlon_kmh ** 2 + vlat_kmh ** 2
    dot_dv  = dx_km * vlon_kmh + dy_km * vlat_kmh
    dist_sq = dx_km ** 2 + dy_km ** 2
    r_sq    = approach_radius_km ** 2

    discriminant = dot_dv ** 2 - vel_sq * (dist_sq - r_sq)
    if discriminant < 0:
        return None  # trajectory misses the approach circle

    sqrt_d = math.sqrt(discriminant)
    t_entry = (dot_dv - sqrt_d) / vel_sq  # smaller root = entry time

    if t_entry <= 0:
        return None  # already inside or moving away

    if t_entry > max_eta_hours:
        return None

    return t_entry
