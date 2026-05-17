"""Storm cluster tracking — HDBSCAN discovery + Kalman filter smoothing + WLS velocity.

Architecture:
  1. Every incoming strike is buffered (lat, lon, country, timestamp).
  2. Every HDBSCAN_INTERVAL_S seconds, HDBSCAN runs on the rolling 30-minute buffer.
     Noise points (label -1) are discarded — they are genuinely isolated strikes.
  3. HDBSCAN clusters are reconciled with existing tracked Cluster objects by
     nearest-centroid matching. Unmatched clusters are created or expired.
  4. Each tracked Cluster runs a 2-state Kalman filter to smooth the centroid
     position across successive HDBSCAN snapshots, then WLS over the smoothed
     history to estimate velocity and ETA.
  5. A covariance ellipse (PCA over the HDBSCAN cluster's points) replaces the
     old circular cluster visualisation.
"""
import asyncio
import logging
import math
import time
from typing import Callable, Dict, List, Optional

import numpy as np
from filterpy.kalman import KalmanFilter
from sklearn.cluster import HDBSCAN

from ..core.config import config
from ..core.utils import calculate_eta, haversine

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
CLUSTER_EXPIRY_SECONDS = 900     # remove a cluster after 15 min without HDBSCAN match
HDBSCAN_INTERVAL_S     = 60.0   # re-cluster every 60 s
STRIKE_WINDOW_S        = 1200.0  # rolling buffer: last 20 min of strikes
MATCH_RADIUS_KM        = 150.0  # max centroid distance to link HDBSCAN result to tracked cluster
EARTH_RADIUS_KM        = 6371.0
MAX_ELLIPSE_KM         = 500.0  # discard spurious clusters wider than this

MIN_CLUSTER_SIZE  = 50   # HDBSCAN: minimum points to form a cluster
MIN_SAMPLES       = 10   # HDBSCAN: minimum neighbours for a core point

MAX_CENTROID_HISTORY  = 30   # KF snapshots to retain
MIN_CENTROIDS_FOR_VEL = 8    # need 8 snapshots (~8 min) before reporting velocity
WLS_WINDOW            = 6    # WLS fit window


# ── Module-level helpers ──────────────────────────────────────────────────────

def _compute_ellipse(lats: np.ndarray, lons: np.ndarray) -> Optional[dict]:
    """2-sigma covariance ellipse of a (lat, lon) point cloud.

    Returns {"a_km", "b_km", "angle_deg"} where a ≥ b are semi-axes and
    angle_deg is the bearing of the major axis (clockwise from north).
    Returns None when fewer than 5 points are available.
    """
    if len(lats) < 5:
        return None

    lat_mean = float(np.mean(lats))
    lon_mean = float(np.mean(lons))  # noqa: F841 — kept for symmetry, not used below

    LAT_KM = 111.0
    lon_km_per_deg = LAT_KM * math.cos(math.radians(lat_mean))

    dlat = (lats - lat_mean) * LAT_KM
    dlon = (lons - float(np.mean(lons))) * lon_km_per_deg

    cov = np.cov(np.vstack([dlat, dlon]))
    if cov.ndim < 2:
        return None

    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues  = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    a_km = max(2.0 * math.sqrt(max(float(eigenvalues[0]), 0.0)), 5.0)
    b_km = max(2.0 * math.sqrt(max(float(eigenvalues[1]), 0.0)), 5.0)

    ev        = eigenvectors[:, 0]
    angle_deg = math.degrees(math.atan2(float(ev[1]), float(ev[0])))

    return {"a_km": round(a_km, 1), "b_km": round(b_km, 1), "angle_deg": round(angle_deg, 1)}


# ── Cluster ───────────────────────────────────────────────────────────────────

class Cluster:
    """Single tracked storm cluster.

    Receives centroid updates from ClusterManager after each HDBSCAN run.
    Maintains a Kalman filter for position smoothing and WLS for velocity.
    """

    def __init__(self, cluster_id: int, lat: float, lon: float):
        self.id             = cluster_id
        self.kf             = self._init_kalman_filter(lat, lon)
        self.strike_count   = 0
        self.last_update    = 0.0
        self.country_counts: Dict[str, int] = {}
        self._centroid_hist: List[tuple] = []   # (lat, lon, timestamp) — KF-smoothed
        self._last_feed     = 0.0
        self._shape: Optional[dict] = None

    # ── Kalman filter ─────────────────────────────────────────────────────────

    def _init_kalman_filter(self, lat: float, lon: float) -> KalmanFilter:
        kf   = KalmanFilter(dim_x=2, dim_z=2)
        kf.H = np.eye(2)
        kf.R = np.eye(2) * 2.0          # ~157 km 1-sigma measurement noise
        kf.P = np.diag([0.25, 0.25])    # ~28 km initial position uncertainty
        kf.Q = np.diag([1e-6, 1e-6])    # base; scaled by dt at each feed
        kf.x = np.array([lat, lon])
        kf.F = np.eye(2)
        return kf

    def _set_Q(self, dt: float):
        self.kf.Q = np.diag([1e-6 * dt, 1e-6 * dt])

    # ── HDBSCAN feed ─────────────────────────────────────────────────────────

    def feed(self, lat: float, lon: float, strike_count: int,
             country_counts: Dict[str, int], shape: Optional[dict], now: float):
        """Update this cluster with a new centroid from the latest HDBSCAN run."""
        self.strike_count   = strike_count
        self.last_update    = now
        self.country_counts = country_counts
        self._shape         = shape

        dt = (now - self._last_feed) if self._last_feed > 0 else HDBSCAN_INTERVAL_S
        dt = max(1.0, min(dt, 600.0))
        self._set_Q(dt)
        self.kf.predict()
        self.kf.update([lat, lon])

        self._centroid_hist.append((float(self.kf.x[0]), float(self.kf.x[1]), now))
        self._centroid_hist = self._centroid_hist[-MAX_CENTROID_HISTORY:]
        self._last_feed = now

    # ── Velocity estimation ───────────────────────────────────────────────────

    def _velocity_wls(self) -> Optional[tuple]:
        """WLS fit over the WLS_WINDOW most recent KF-smoothed centroid snapshots.

        Returns (vlat_kmh, vlon_kmh, speed_kmh, bearing_deg) or None.
        """
        hist = self._centroid_hist
        if len(hist) < MIN_CENTROIDS_FOR_VEL:
            return None

        hist    = hist[-WLS_WINDOW:]
        t0      = hist[0][2]
        ages_h  = [(h[2] - t0) / 3600.0 for h in hist]
        now_t   = hist[-1][2]
        weights = [math.exp(-math.log(2) * (now_t - h[2]) / 1800.0) for h in hist]
        lats    = [h[0] for h in hist]
        lons    = [h[1] for h in hist]

        W     = sum(weights)
        Wt    = sum(weights[i] * ages_h[i]            for i in range(len(hist)))
        Wt2   = sum(weights[i] * ages_h[i] ** 2       for i in range(len(hist)))
        WLat  = sum(weights[i] * lats[i]              for i in range(len(hist)))
        WtLat = sum(weights[i] * ages_h[i] * lats[i]  for i in range(len(hist)))
        WLon  = sum(weights[i] * lons[i]              for i in range(len(hist)))
        WtLon = sum(weights[i] * ages_h[i] * lons[i]  for i in range(len(hist)))

        denom = W * Wt2 - Wt ** 2
        if abs(denom) < 1e-12:
            return None

        vlat_h = (W * WtLat - Wt * WLat) / denom
        vlon_h = (W * WtLon - Wt * WLon) / denom

        LAT_KM   = 111.0
        lat_mean = sum(lats) / len(lats)
        lon_km   = LAT_KM * math.cos(math.radians(lat_mean))

        vlat_kmh    = vlat_h * LAT_KM
        vlon_kmh    = vlon_h * lon_km
        speed_kmh   = math.hypot(vlat_kmh, vlon_kmh)
        bearing_deg = math.degrees(math.atan2(vlon_kmh, vlat_kmh)) % 360

        return (vlat_kmh, vlon_kmh, speed_kmh, bearing_deg)

    # ── State output ──────────────────────────────────────────────────────────

    def get_state(self, target_lat: float, target_lon: float) -> Dict:
        cx = float(self.kf.x[0])
        cy = float(self.kf.x[1])

        vel = self._velocity_wls()
        if vel is not None:
            vlat_kmh, vlon_kmh, speed_kmh, bearing_deg = vel
        else:
            vlat_kmh, vlon_kmh, speed_kmh, bearing_deg = 0.0, 0.0, 0.0, 0.0

        country = (
            max(self.country_counts, key=self.country_counts.get)
            if self.country_counts else None
        )

        dist_to_target = haversine(cx, cy, target_lat, target_lon)

        eta_hours = None
        if vel is not None and dist_to_target <= 500.0:
            eta_hours = calculate_eta(
                cx, cy, target_lat, target_lon,
                vlat_kmh, vlon_kmh, speed_kmh,
                approach_radius_km=100.0,
                max_eta_hours=3.0,
            )

        return {
            "id":                self.id,
            "lat":               cx,
            "lon":               cy,
            "vlat_kmh":          vlat_kmh,
            "vlon_kmh":          vlon_kmh,
            "speed_kmh":         speed_kmh,
            "bearing_deg":       bearing_deg,
            "strike_count":      self.strike_count,
            "eta_hours":         eta_hours,
            "dist_to_target_km": dist_to_target,
            "country":           country,
            "shape":             self._shape,
        }


# ── ClusterManager ────────────────────────────────────────────────────────────

class ClusterManager:
    """Manage tracked storm clusters via periodic HDBSCAN re-clustering."""

    def __init__(self, alert_radius_km: float = 50.0):
        self.clusters: Dict[int, Cluster] = {}
        self.alert_radius_km = alert_radius_km
        self.lock            = asyncio.Lock()
        self.next_cluster_id = 0
        self._strike_buf: List[tuple] = []   # (lat, lon, country, timestamp)
        self._broadcast_cb: Optional[Callable] = None
        self._task: Optional[asyncio.Task] = None

    def set_broadcast_callback(self, cb: Callable):
        """Register async callback(clusters, removed_ids) called after each HDBSCAN run."""
        self._broadcast_cb = cb

    async def add_strike(self, lat: float, lon: float, country: Optional[str] = None):
        """Buffer an incoming strike for the next HDBSCAN run.

        Only strikes within the tracking radius are buffered — global data is
        kept for the strike map but there is no value in tracking storm clusters
        10,000 km away from the user's target.
        Tracking radius = 2× obs_radius, minimum 1500 km.  At 100 km/h that
        gives at least 15 hours of lead time before a storm reaches the target.
        """
        tracking_radius = max(config.OBS_RADIUS_KM * 2, 1500.0)
        if haversine(lat, lon, config.TARGET_LAT, config.TARGET_LON) > tracking_radius:
            return
        async with self.lock:
            self._strike_buf.append((lat, lon, country, time.time()))

    async def start(self):
        """Launch the periodic HDBSCAN background task."""
        self._task = asyncio.create_task(self._hdbscan_loop())
        logger.info("HDBSCAN cluster tracking started")

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def get_all_clusters(self) -> list:
        async with self.lock:
            return [c.get_state(config.TARGET_LAT, config.TARGET_LON)
                    for c in self.clusters.values()]

    # ── Background task ───────────────────────────────────────────────────────

    async def _hdbscan_loop(self):
        while True:
            await asyncio.sleep(HDBSCAN_INTERVAL_S)
            try:
                await self._run_hdbscan()
            except Exception:
                logger.exception("HDBSCAN run failed")

    async def _run_hdbscan(self):
        now    = time.time()
        cutoff = now - STRIKE_WINDOW_S

        async with self.lock:
            self._strike_buf = [s for s in self._strike_buf if s[3] >= cutoff]
            pts = list(self._strike_buf)

        if len(pts) < MIN_CLUSTER_SIZE:
            return

        coords_rad = np.radians(np.array([(p[0], p[1]) for p in pts]))

        clusterer = HDBSCAN(
            min_cluster_size=MIN_CLUSTER_SIZE,
            min_samples=MIN_SAMPLES,
            metric='haversine',
        )

        loop   = asyncio.get_running_loop()
        labels = await loop.run_in_executor(None, clusterer.fit_predict, coords_rad)

        # Aggregate strikes by label
        label_map: Dict[int, dict] = {}
        for i, label in enumerate(labels):
            if label < 0:
                continue  # noise point — discard
            if label not in label_map:
                label_map[label] = {"lats": [], "lons": [], "countries": {}}
            label_map[label]["lats"].append(pts[i][0])
            label_map[label]["lons"].append(pts[i][1])
            c = pts[i][2]
            if c and len(c) == 2:
                d = label_map[label]["countries"]
                d[c] = d.get(c, 0) + 1

        if not label_map:
            return

        new_clusters = []
        for data in label_map.values():
            lats = np.array(data["lats"])
            lons = np.array(data["lons"])
            shape = _compute_ellipse(lats, lons)
            # Discard spurious clusters that span an unrealistically large area —
            # these are HDBSCAN artefacts bridging multiple unrelated storm systems.
            if shape and shape["a_km"] > MAX_ELLIPSE_KM:
                continue
            new_clusters.append({
                "lat":       float(np.mean(lats)),
                "lon":       float(np.mean(lons)),
                "count":     len(lats),
                "countries": data["countries"],
                "shape":     shape,
            })

        async with self.lock:
            removed = self._reconcile(new_clusters, now)

        logger.info(
            f"HDBSCAN: {len(pts)} strikes → {len(new_clusters)} clusters "
            f"({len(pts) - sum(1 for lbl in labels if lbl >= 0)} noise); "
            f"{len(removed)} expired"
        )

        if self._broadcast_cb:
            clusters = await self.get_all_clusters()
            await self._broadcast_cb(clusters, removed)

    def _reconcile(self, new_clusters: list, now: float) -> List[int]:
        """Match HDBSCAN clusters to existing tracked clusters (greedy nearest-centroid).

        Returns list of expired cluster IDs.
        """
        matched_existing: set = set()
        assignments: Dict[int, int] = {}   # new_idx → cluster_id

        for new_idx, nc in enumerate(new_clusters):
            best_dist = MATCH_RADIUS_KM
            best_cid  = None
            for cid, cluster in self.clusters.items():
                if cid in matched_existing:
                    continue
                dist = haversine(nc["lat"], nc["lon"],
                                 float(cluster.kf.x[0]), float(cluster.kf.x[1]))
                if dist < best_dist:
                    best_dist = dist
                    best_cid  = cid
            if best_cid is not None:
                assignments[new_idx] = best_cid
                matched_existing.add(best_cid)

        # Update matched
        for new_idx, cid in assignments.items():
            nc = new_clusters[new_idx]
            self.clusters[cid].feed(
                nc["lat"], nc["lon"], nc["count"], nc["countries"], nc["shape"], now
            )

        # Create unmatched
        for new_idx, nc in enumerate(new_clusters):
            if new_idx not in assignments:
                cid = self.next_cluster_id
                self.next_cluster_id += 1
                c = Cluster(cid, nc["lat"], nc["lon"])
                c.feed(nc["lat"], nc["lon"], nc["count"], nc["countries"], nc["shape"], now)
                self.clusters[cid] = c
                logger.info(f"New cluster {cid} at ({nc['lat']:.3f}, {nc['lon']:.3f})")

        # Expire stale clusters not seen in recent HDBSCAN runs
        purged = []
        for cid in list(self.clusters):
            if cid not in matched_existing:
                if now - self.clusters[cid].last_update > CLUSTER_EXPIRY_SECONDS:
                    logger.info(f"Cluster {cid} expired")
                    del self.clusters[cid]
                    purged.append(cid)

        return purged
