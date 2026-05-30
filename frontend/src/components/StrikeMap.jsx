import { useEffect, useRef, useCallback, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import './StrikeMap.css';
import { MIN_CLUSTER_STRIKES } from '../constants';

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const TILE_CONFIGS = {
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    options: {
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics',
      maxZoom: 19,
    },
  },
  street: {
    url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    options: {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    },
  },
};

// Transparent overlay: country borders, names, and capitals — designed by ESRI
// to sit on top of World Imagery. Only applied in satellite mode; street tiles
// already include labels.
const ESRI_LABELS = {
  url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
  options: { attribution: '', maxZoom: 19, pane: 'labelsPane' },
};

// lightningmaps.org-style color progression — yellow → orange → red → dark-brown
function getStrikeStyle(age_ms) {
  const s = age_ms / 1000;
  const m = s / 60;

  if (s < 30) {
    return { fillColor: '#ffe000', color: '#ffaa00', weight: 1.5, fillOpacity: 1.0,  opacity: 1.0, radius: 5 };
  }
  if (m < 2) {
    return { fillColor: '#ffc000', color: '#ff8800', weight: 1.0, fillOpacity: 0.95, opacity: 1.0, radius: 5 };
  }
  if (m < 5) {
    const t = (m - 2) / 3;
    return { fillColor: '#ff9000', color: '#ff5500', weight: 0.8, fillOpacity: 0.90 - t * 0.15, opacity: 0.95, radius: 4 };
  }
  if (m < 15) {
    const t = (m - 5) / 10;
    return { fillColor: '#ff5000', color: '#cc2200', weight: 0.5, fillOpacity: Math.max(0.75 - t * 0.45, 0.20), opacity: Math.max(0.80 - t * 0.40, 0.25), radius: 4 };
  }
  const t = Math.min((m - 15) / 15, 1.0);
  return { fillColor: '#aa2200', color: '#661100', weight: 0.5, fillOpacity: Math.max(0.25 - t * 0.20, 0.04), opacity: Math.max(0.30 - t * 0.25, 0.05), radius: 3 };
}

function timeAgo(ms) {
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 5)  return 'just now';
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s ago`;
  return `${Math.floor(m / 60)}h ${m % 60}m ago`;
}

// Build an N-point polygon approximating a geographic ellipse.
// a_km/b_km are semi-axes; angle_deg is the bearing of the major axis (CW from north).
function ellipsePoints(centerLat, centerLon, aKm, bKm, angleDeg, nPts = 48) {
  const LAT_KM = 111.0;
  const lonKmPerDeg = LAT_KM * Math.cos(centerLat * Math.PI / 180);
  const angleRad = angleDeg * Math.PI / 180;  // bearing from north → radians
  const cosA = Math.cos(angleRad);  // northward component of major axis
  const sinA = Math.sin(angleRad);  // eastward  component of major axis
  const pts = [];
  for (let i = 0; i < nPts; i++) {
    const theta = (i / nPts) * 2 * Math.PI;
    const t = aKm * Math.cos(theta);
    const s = bKm * Math.sin(theta);
    const dlat_km = t * cosA - s * sinA;
    const dlon_km = t * sinA + s * cosA;
    pts.push([centerLat + dlat_km / LAT_KM, centerLon + dlon_km / lonKmPerDeg]);
  }
  return pts;
}

// Confidence-based cluster circle style — more strikes = more stable WLS estimate.
function clusterStyle(strikeCount, isSelected) {
  let fill, stroke;
  if (isSelected) {
    fill = '#3b82f6'; stroke = '#93c5fd';
  } else if (strikeCount >= 80) {
    fill = '#22c55e'; stroke = '#16a34a';   // green — high confidence
  } else if (strikeCount >= 40) {
    fill = '#eab308'; stroke = '#ca8a04';   // yellow — moderate
  } else if (strikeCount >= 20) {
    fill = '#f97316'; stroke = '#ea580c';   // orange — low-moderate
  } else {
    fill = '#ef4444'; stroke = '#dc2626';   // red — just forming, low confidence
  }
  return { fillColor: fill, color: stroke, weight: isSelected ? 3 : 2, fillOpacity: isSelected ? 0.75 : 0.6, opacity: 0.9 };
}

// SVG arrow anchored at cluster center pointing in `bearing` (clockwise from north).
// Uses a properly-sized SVG viewport (140×140) with translate+rotate so the content
// is drawn within a real viewport — avoids the clipping issue with 0×0 divIcons.
// iconAnchor [70,70] centers the SVG on the cluster's lat/lon position.
// zoomScale = Math.pow(1.3, zoom-6) — same factor used for circle radius so
// arrow and circle shrink/grow together when the user zooms in or out.
function clusterArrowIcon(bearing, speed, isSelected, zoomScale = 1) {
  const scale   = Math.max(0.3, Math.min(zoomScale, 2.5));
  const baseLen = 18 + Math.min(speed / 2.5, 32);
  const len     = Math.max(8,  Math.round(baseLen * scale));
  const head    = Math.max(4,  Math.round(10 * scale));
  const hw      = Math.max(3,  Math.round(6  * scale));
  const sw      = Math.max(1,  Math.round(2.5 * scale));
  const S       = Math.max(50, Math.min(Math.round(140 * scale), 260));
  const cx      = S / 2;
  const cy      = S / 2;
  const col     = isSelected ? '#93c5fd' : '#ffffff';
  const brg     = Math.round(bearing);
  return L.divIcon({
    className:  '',
    iconSize:   [S, S],
    iconAnchor: [cx, cy],
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="${S}" height="${S}"
               style="pointer-events:none;overflow:visible">
      <g transform="translate(${cx},${cy}) rotate(${brg})">
        <line x1="0" y1="${Math.round(6*scale)}" x2="0" y2="${-len}"
              stroke="rgba(0,0,0,0.55)" stroke-width="${sw*2}" stroke-linecap="round"/>
        <line x1="0" y1="${Math.round(6*scale)}" x2="0" y2="${-len}"
              stroke="${col}" stroke-width="${sw}" stroke-linecap="round"/>
        <polygon points="0,${-(len+head)} ${-hw},${-len} ${hw},${-len}"
                 fill="rgba(0,0,0,0.55)" stroke="rgba(0,0,0,0.55)"
                 stroke-width="${Math.max(1,sw-1)}" stroke-linejoin="round"/>
        <polygon points="0,${-(len+head)} ${-hw},${-len} ${hw},${-len}" fill="${col}"/>
      </g>
      <text x="${cx}" y="${cy + Math.max(12, Math.round(18*scale))}"
            text-anchor="middle" dominant-baseline="hanging"
            font-size="${Math.max(7, Math.round(9*scale))}" font-weight="700"
            fill="white" font-family="sans-serif"
            style="paint-order:stroke;stroke:rgba(0,0,0,0.85);stroke-width:${sw+0.5}px">
        ${Math.round(speed)} km/h
      </text>
    </svg>`,
  });
}

function StrikeMap({ strikes, clusters, settings, selectedStrike, onPinDone, mapMode, onStrikeSelect, selectedCluster, onClusterSelect }) {
  const mapRef              = useRef(null);
  const mapInstanceRef      = useRef(null);
  const tileLayerRef        = useRef(null);
  const labelsLayerRef      = useRef(null);
  const strikeLayersRef     = useRef([]);
  const clusterLayersRef    = useRef([]);
  const targetMarkerRef     = useRef(null);
  const alertCircleRef      = useRef(null);
  const clusterHistoryRef   = useRef({});
  const strikesRef          = useRef(strikes);
  const mapModeRef          = useRef(mapMode);
  const onStrikeSelectRef   = useRef(onStrikeSelect);
  const onClusterSelectRef  = useRef(onClusterSelect);

  // ── Animation ring state (lightningmaps.org style) ───────────────────────
  const animatedStrikesRef = useRef(new Set());
  const animRingsRef       = useRef([]);
  const animRafRef         = useRef(null);

  // ── Tile style + zoom state ──────────────────────────────────────────────
  const [tileStyle, setTileStyle] = useState('satellite');
  const [mapZoom, setMapZoom]     = useState(6);

  strikesRef.current           = strikes;
  mapModeRef.current           = mapMode;
  onStrikeSelectRef.current    = onStrikeSelect;
  onClusterSelectRef.current   = onClusterSelect;

  // rAF loop — ticks every frame while any rings are active.
  // Ring grows from r=6 to r=60 px over ~2 s, then fades and disappears.
  // smoothy divisor: 43 = original lightningmaps value scaled to achieve ~2 s
  // total duration at 60 fps. Reduce divisor to speed up, increase to slow down.
  const tickAnims = useCallback(() => {
    const map = mapInstanceRef.current;
    if (!map) { animRafRef.current = null; return; }

    const now = Date.now();
    let activeCount = 0;

    animRingsRef.current = animRingsRef.current.filter(ring => {
      const smoothy  = (now - ring.startTime) / 43;
      ring.startTime = now;
      ring.radius    = ring.radius * Math.pow(1.04, smoothy);
      const r = ring.radius;

      if (r >= 60 || isNaN(r)) {
        if (map.hasLayer(ring.marker)) map.removeLayer(ring.marker);
        return false;
      }
      // Fade stroke over the outer third of the travel (40 → 60 px)
      const op = r > 40 ? Math.max(0, 1 - (r - 40) / 20) : 1.0;
      const wt = r > 40 ? Math.max(0, 2.0 * (1 - (r - 40) / 20)) : 2.0;
      ring.marker.setStyle({ radius: Math.round(r), opacity: op, weight: wt });
      activeCount++;
      return true;
    });

    if (activeCount > 0) {
      animRafRef.current = requestAnimationFrame(tickAnims);
    } else {
      animRafRef.current = null;
    }
  }, []); // stable — only accesses refs

  // Spawn one expanding ring, or reset/suppress based on proximity and recency.
  //
  // Rules (applied in order):
  //  1. If a ring is active within MERGE_PX AND was spawned/reset < COOLDOWN_MS ago
  //     → suppress entirely (the area just lit up, no need for another ring yet).
  //  2. If a ring is active within MERGE_PX AND cooldown has elapsed
  //     → reset that ring to the new position (represents the latest strike).
  //  3. No nearby ring → spawn a fresh ring.
  //
  // MERGE_PX = 40 px ≈ 88 km at zoom 5, 22 km at zoom 7, 5.5 km at zoom 9.
  // COOLDOWN_MS = 1500 ms — minimum gap between rings at the same screen spot.
  //
  // Note: ring.startTime is updated every rAF frame (used for smooth expansion),
  // so a separate ring.lastSpawnTime tracks when the ring was last spawned/reset.
  const spawnRing = useCallback((lat, lon) => {
    const map = mapInstanceRef.current;
    if (!map) return;

    const MERGE_PX   = 40;
    const COOLDOWN_MS = 1500;
    const now = Date.now();
    const pt  = map.latLngToContainerPoint([lat, lon]);

    for (const ring of animRingsRef.current) {
      const rpt = map.latLngToContainerPoint(ring.marker.getLatLng());
      if (Math.hypot(pt.x - rpt.x, pt.y - rpt.y) <= MERGE_PX) {
        if (now - ring.lastSpawnTime < COOLDOWN_MS) {
          return; // still within cooldown — suppress
        }
        // Cooldown elapsed: reset ring to the new strike position
        ring.radius        = 6;
        ring.startTime     = now;
        ring.lastSpawnTime = now;
        ring.marker.setLatLng([lat, lon]);
        ring.marker.setStyle({ radius: 6, opacity: 1.0, weight: 2.0 });
        if (!animRafRef.current) animRafRef.current = requestAnimationFrame(tickAnims);
        return;
      }
    }

    // No nearby ring — spawn a fresh one
    const marker = L.circleMarker([lat, lon], {
      radius: 6, stroke: true, color: '#ffffff', opacity: 1.0,
      weight: 2.0, fillOpacity: 0, interactive: false,
      pane: 'animRingPane',
    }).addTo(map);
    animRingsRef.current.push({ marker, radius: 6, startTime: now, lastSpawnTime: now });
    if (!animRafRef.current) animRafRef.current = requestAnimationFrame(tickAnims);
  }, [tickAnims]);

  const spawnRingRef = useRef(spawnRing);
  spawnRingRef.current = spawnRing;

  // Full rebuild of strike markers — always clears and re-creates from scratch.
  // Viewport-filtered so only markers in the visible area are added.
  // SVG renderer (Leaflet default) — no canvas-initialization timing issues.
  const rebuildStrikeMarkers = useCallback(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    strikeLayersRef.current.forEach(l => map.removeLayer(l));
    strikeLayersRef.current = [];

    if (mapModeRef.current !== 'points') return;

    const now = Date.now();

    // getBounds() can return a near-zero or inverted area before Leaflet has
    // measured the container. Validate by checking it spans a real geographic area.
    const rawBounds = map.getBounds();
    const latSpan   = rawBounds.getNorth() - rawBounds.getSouth();
    const lngSpan   = rawBounds.getEast()  - rawBounds.getWest();
    const boundsOk  = latSpan > 1 && lngSpan > 1;

    const visible = boundsOk
      ? strikesRef.current.filter(s => rawBounds.pad(0.4).contains([s.lat, s.lon]))
      : strikesRef.current.slice(-2000);

    // Prune the animated-strikes set to avoid unbounded growth
    if (animatedStrikesRef.current.size > 5000) {
      const currentKeys = new Set(strikesRef.current.map(s => s._key));
      for (const k of animatedStrikesRef.current) {
        if (!currentKeys.has(k)) animatedStrikesRef.current.delete(k);
      }
    }

    visible.forEach(strike => {
      const age     = now - strike.time_ms;
      const tooltip =
        `${strike.lat.toFixed(3)}\xb0, ${strike.lon.toFixed(3)}\xb0<br/>` +
        `${timeAgo(strike.time_ms)} \xb7 ${new Date(strike.time_ms).toLocaleTimeString()}` +
        (strike.country ? `<br/>${strike.country}` : '');

      const layer = L.circleMarker([strike.lat, strike.lon], getStrikeStyle(age)).addTo(map);
      layer.bindTooltip(tooltip, { sticky: false, direction: 'top', opacity: 0.92 });
      layer.on('click', () => onStrikeSelectRef.current?.(strike));
      strikeLayersRef.current.push(layer);

      // White ring for strikes ≤ 10 s old — spawned once per strike key.
      if (age < 10_000 && !animatedStrikesRef.current.has(strike._key)) {
        animatedStrikesRef.current.add(strike._key);
        spawnRingRef.current(strike.lat, strike.lon);
      }
    });
  }, []);

  // ── Effect 1: init map ───────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return;
    const map = L.map(mapRef.current).setView([settings.target_lat, settings.target_lon], 6);

    // labelsPane: sits between the tile layer (200) and data overlays (400+),
    // so borders/names appear above imagery but behind strike markers.
    map.createPane('labelsPane');
    map.getPane('labelsPane').style.zIndex = 250;
    map.getPane('labelsPane').style.pointerEvents = 'none';

    // animRingPane: above overlayPane (400) and markerPane (600) so rings are
    // never hidden behind strike dots or cluster circles.
    map.createPane('animRingPane');
    map.getPane('animRingPane').style.zIndex = 620;
    map.getPane('animRingPane').style.pointerEvents = 'none';

    mapInstanceRef.current = map;
    map.whenReady(() => rebuildStrikeMarkers());
    map.on('zoomend', () => setMapZoom(map.getZoom()));
    return () => {
      if (animRafRef.current) { cancelAnimationFrame(animRafRef.current); animRafRef.current = null; }
      labelsLayerRef.current  = null;
      tileLayerRef.current    = null;
      targetMarkerRef.current = null;
      alertCircleRef.current  = null;
      map.remove();
      mapInstanceRef.current  = null;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Effect: swap tile layer + labels overlay when tileStyle changes ────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Swap base tile layer
    if (tileLayerRef.current) { map.removeLayer(tileLayerRef.current); tileLayerRef.current = null; }
    const cfg = TILE_CONFIGS[tileStyle];
    tileLayerRef.current = L.tileLayer(cfg.url, cfg.options).addTo(map);
    tileLayerRef.current.bringToBack();

    // Labels overlay: only for satellite — street tiles already include labels
    if (labelsLayerRef.current) { map.removeLayer(labelsLayerRef.current); labelsLayerRef.current = null; }
    if (tileStyle === 'satellite') {
      labelsLayerRef.current = L.tileLayer(ESRI_LABELS.url, ESRI_LABELS.options).addTo(map);
    }
  }, [tileStyle]);

  // ── Effect 2: settings → target marker + alert circle ───────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const latLng = [settings.target_lat, settings.target_lon];
    const radiusMeters = settings.alert_radius_km * 1000;
    if (targetMarkerRef.current) {
      targetMarkerRef.current.setLatLng(latLng);
      targetMarkerRef.current.setPopupContent(`${settings.target_name} (Target)`);
    } else {
      const crosshairIcon = L.divIcon({
        className: '',
        iconSize: [36, 36],
        iconAnchor: [18, 18],
        html: `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" style="overflow:visible;pointer-events:none">
          <circle cx="18" cy="18" r="14" fill="none" stroke="white"  stroke-width="4"   opacity="0.5"/>
          <circle cx="18" cy="18" r="14" fill="none" stroke="black"  stroke-width="2"   opacity="0.95"/>
          <circle cx="18" cy="18" r="4"  fill="white" opacity="0.6"/>
          <circle cx="18" cy="18" r="4"  fill="black" opacity="0.95"/>
          <line x1="4"  y1="18" x2="12" y2="18" stroke="white" stroke-width="3"   opacity="0.5"/>
          <line x1="4"  y1="18" x2="12" y2="18" stroke="black" stroke-width="1.5"/>
          <line x1="24" y1="18" x2="32" y2="18" stroke="white" stroke-width="3"   opacity="0.5"/>
          <line x1="24" y1="18" x2="32" y2="18" stroke="black" stroke-width="1.5"/>
          <line x1="18" y1="4"  x2="18" y2="12" stroke="white" stroke-width="3"   opacity="0.5"/>
          <line x1="18" y1="4"  x2="18" y2="12" stroke="black" stroke-width="1.5"/>
          <line x1="18" y1="24" x2="18" y2="32" stroke="white" stroke-width="3"   opacity="0.5"/>
          <line x1="18" y1="24" x2="18" y2="32" stroke="black" stroke-width="1.5"/>
        </svg>`,
      });
      targetMarkerRef.current = L.marker(latLng, { icon: crosshairIcon, zIndexOffset: 1000 })
        .addTo(map).bindPopup(`<strong>${settings.target_name}</strong><br/>Target location`);
    }
    // Inner alert circle (alert_radius_km)
    if (alertCircleRef.current) {
      alertCircleRef.current.setLatLng(latLng);
      alertCircleRef.current.setRadius(radiusMeters);
    } else {
      alertCircleRef.current = L.circle(latLng, {
        radius: radiusMeters,
        color: '#000000',
        weight: 2,
        opacity: 0.65,
        fill: true,
        fillColor: '#000000',
        fillOpacity: 0.05,
        dashArray: '4 4',
      }).addTo(map);
    }
  }, [settings]);

  // ── Effect 3: mode change → immediate rebuild ────────────────────────────
  // `strikes` is intentionally excluded: rebuildStrikeMarkers reads strikesRef.current
  // (kept current on every render) so the 2 s interval below provides live updates
  // without triggering a full SVG rebuild on every incoming strike (5–10×/sec).
  useEffect(() => { rebuildStrikeMarkers(); }, [mapMode, rebuildStrikeMarkers]);

  // ── Effect 4: pan / zoom → rebuild for viewport sync ────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    map.on('moveend', rebuildStrikeMarkers);
    return () => { map.off('moveend', rebuildStrikeMarkers); };
  }, [rebuildStrikeMarkers]);

  // ── Effect 5: clusters ────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    clusterLayersRef.current.forEach(m => map.removeLayer(m));
    clusterLayersRef.current = [];
    if (mapMode !== 'cluster') return;

    // Update position history for trajectory lines
    const nowMs = Date.now();
    const activeIds = new Set(clusters.map(c => c.id));
    for (const id of Object.keys(clusterHistoryRef.current)) {
      if (!activeIds.has(Number(id))) delete clusterHistoryRef.current[id];
    }
    clusters.forEach(cluster => {
      if (cluster.strike_count < MIN_CLUSTER_STRIKES) return;
      const hist = clusterHistoryRef.current[cluster.id] || [];
      const recent = hist.filter(p => nowMs - p.time < 20 * 60_000);
      const last = recent[recent.length - 1];
      if (!last || Math.abs(cluster.lat - last.lat) > 0.005 || Math.abs(cluster.lon - last.lon) > 0.005) {
        recent.push({ lat: cluster.lat, lon: cluster.lon, time: nowMs });
      }
      clusterHistoryRef.current[cluster.id] = recent;
    });

    clusters.forEach(cluster => {
      if (cluster.strike_count < MIN_CLUSTER_STRIKES) return;

      const isSelected = selectedCluster?.id === cluster.id;
      const zoomScale = Math.pow(1.35, mapZoom - 6);
      const style = clusterStyle(cluster.strike_count, isSelected);

      let marker;
      if (cluster.shape) {
        const { a_km, b_km, angle_deg } = cluster.shape;
        const pts = ellipsePoints(cluster.lat, cluster.lon, a_km, b_km, angle_deg);
        marker = L.polygon(pts, { ...style, weight: isSelected ? 2.5 : 1.5 }).addTo(map);
      } else {
        // Fallback circle before enough strikes to compute an ellipse
        const radius = Math.max(4, Math.min(Math.log(cluster.strike_count + 1) * 6 * zoomScale, 48));
        marker = L.circleMarker([cluster.lat, cluster.lon], { radius, ...style }).addTo(map);
      }

      const distStr = cluster.dist_to_target_km != null
        ? ` \xb7 ${Math.round(cluster.dist_to_target_km)} km from target`
        : '';
      const bearingStr = cluster.bearing_deg != null && cluster.speed_kmh > 1
        ? ` (${Math.round(cluster.bearing_deg)}\xb0)`
        : '';
      let tip =
        `<strong>Storm Cluster #${cluster.id}</strong><br/>` +
        `${cluster.strike_count} strikes` +
        (cluster.speed_kmh != null ? ` \xb7 ${cluster.speed_kmh.toFixed(1)} km/h${bearingStr}` : '') +
        `<br/>${cluster.lat.toFixed(3)}\xb0, ${cluster.lon.toFixed(3)}\xb0${distStr}`;
      if (cluster.eta_hours != null) {
        const etaColor = cluster.eta_hours < 1 ? '#ef4444' : '#f59e0b';
        tip += `<br/><span style="color:${etaColor}">ETA: ${cluster.eta_hours.toFixed(2)} h</span>`;
      }
      marker.bindTooltip(tip, { sticky: false, direction: 'top', opacity: 0.92 });
      marker.on('click', () => {
        const cur = selectedCluster?.id === cluster.id ? null : cluster;
        onClusterSelectRef.current?.(cur);
      });
      clusterLayersRef.current.push(marker);

      // Trajectory: history line + extrapolation dashed line for nearby clusters
      const isNearby = cluster.dist_to_target_km != null && cluster.dist_to_target_km <= 500;
      if (isNearby && cluster.vlat_kmh != null) {
        const tCol  = isSelected ? '#93c5fd' : '#facc15'; // yellow — visible on satellite
        const clHist = clusterHistoryRef.current[cluster.id] || [];
        if (clHist.length >= 2) {
          const histLine = L.polyline(clHist.map(p => [p.lat, p.lon]), {
            color: tCol, weight: 2, opacity: 0.5, interactive: false,
          }).addTo(map);
          clusterLayersRef.current.push(histLine);
        }
        // Extrapolate forward: use actual velocity or a minimum 100 km stub to stay visible
        const LAT_KM  = 111.0;
        const lonKm   = LAT_KM * Math.cos(cluster.lat * Math.PI / 180);
        const speed   = cluster.speed_kmh || 0;
        const hours   = speed > 1 ? Math.min(120 / speed, 3.0) : 0; // aim for ~120 km stub, cap 3 h
        const vlat    = cluster.vlat_kmh || 0;
        const vlon    = cluster.vlon_kmh || 0;
        const norm    = Math.hypot(vlat, vlon) || 1;
        // Ensure stub is at least 100 km long so it's visible at any zoom
        const stubKm  = Math.max(speed * hours, 100);
        const futLat  = cluster.lat + (vlat / norm) * stubKm / LAT_KM;
        const futLon  = cluster.lon + (vlon / norm) * stubKm / lonKm;
        const extLine = L.polyline([[cluster.lat, cluster.lon], [futLat, futLon]], {
          color: tCol, weight: 2, opacity: 0.8, dashArray: '6 8', interactive: false,
        }).addTo(map);
        clusterLayersRef.current.push(extLine);
      }

      // Directional arrow — only for clusters with a realistic, meaningful speed.
      // Upper bound (180 km/h) filters WLS artefacts on newly-tracked clusters.
      if (cluster.speed_kmh >= 10 && cluster.speed_kmh <= 180 && cluster.bearing_deg != null) {
        const arrowMarker = L.marker([cluster.lat, cluster.lon], {
          icon: clusterArrowIcon(cluster.bearing_deg, cluster.speed_kmh, isSelected, zoomScale),
          interactive: false,
          zIndexOffset: 500,
        }).addTo(map);
        clusterLayersRef.current.push(arrowMarker);
      }
    });
  }, [clusters, mapMode, selectedCluster, mapZoom]);

  // ── Effect: pan to selected cluster ─────────────────────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !selectedCluster) return;
    const latlng = L.latLng(selectedCluster.lat, selectedCluster.lon);
    if (!map.getBounds().contains(latlng)) {
      map.panTo(latlng, { animate: true, duration: 0.5 });
    }
  }, [selectedCluster]);

  // ── Effect 6: selectedStrike → pulsing pin for 3 s ───────────────────────
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !selectedStrike) return;
    const latlng = L.latLng(selectedStrike.lat, selectedStrike.lon);
    if (!map.getBounds().contains(latlng)) map.panTo(latlng, { animate: true, duration: 0.5 });
    const icon = L.divIcon({
      className: '',
      html: `<div class="strike-pin">
               <div class="strike-pin-ring"></div>
               <div class="strike-pin-ring strike-pin-ring-2"></div>
               <div class="strike-pin-core"></div>
             </div>`,
      iconSize: [50, 50], iconAnchor: [25, 25],
    });
    const marker = L.marker(latlng, { icon, zIndexOffset: 9999 }).addTo(map);
    const fadeTimer = setTimeout(() => {
      const el = marker.getElement();
      if (el) { el.style.transition = 'opacity 0.5s ease-out'; el.style.opacity = '0'; }
    }, 2500);
    const removeTimer = setTimeout(() => { map.removeLayer(marker); onPinDone?.(); }, 3000);
    return () => {
      clearTimeout(fadeTimer); clearTimeout(removeTimer);
      if (map.hasLayer(marker)) map.removeLayer(marker);
    };
  }, [selectedStrike, onPinDone]);

  // ── Effect 7: 2 s ticker — live strike updates + age-based style refresh ──
  // Reduced from 15 s so new strikes appear promptly. The low rebuild rate
  // (was 5–10×/sec on every strike) is now the main lag fix.
  useEffect(() => {
    const timer = setInterval(rebuildStrikeMarkers, 2_000);
    return () => clearInterval(timer);
  }, [rebuildStrikeMarkers]);

  return (
    <div className="strike-map">
      <div ref={mapRef} className="strike-map-inner"></div>

      <button
        className="tile-toggle-btn"
        onClick={() => setTileStyle(s => s === 'satellite' ? 'street' : 'satellite')}
        title="Toggle map style"
      >
        {tileStyle === 'satellite' ? '🗺️ Street' : '🛰️ Satellite'}
      </button>

      <div className="strike-age-legend">
        <div className="legend-title">Strike Age</div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: 'transparent', border: '1.5px solid #fff', boxSizing: 'border-box' }}></span>
          <span>just now</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: '#ffe000', boxShadow: '0 0 0 1.5px rgba(255,200,0,0.7)' }}></span>
          <span>&lt; 30 s</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: '#ff9000' }}></span>
          <span>&lt; 5 min</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: '#ff5000', opacity: 0.7 }}></span>
          <span>&lt; 15 min</span>
        </div>
        <div className="legend-row">
          <span className="legend-dot" style={{ background: '#aa2200', opacity: 0.35 }}></span>
          <span>&lt; 30 min</span>
        </div>
      </div>
    </div>
  );
}

export default StrikeMap;
