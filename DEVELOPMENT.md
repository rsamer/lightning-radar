# Development Guide

## Environment Setup

### Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda
- Git

### First-time setup

```bash
conda env create -f environment.yml
conda activate lightning-radar
cd frontend && npm install && cd ..
cp .env.example .env
```

### Daily workflow

```bash
conda activate lightning-radar
./start.sh          # starts backend on :8000 and Vite dev server on :5173
```

## Project Layout

```
backend/app/
├── main.py              # FastAPI app, lifespan hooks, broadcast callback
├── core/
│   ├── config.py        # Config dataclass (mutate fields for runtime changes)
│   ├── database.py      # SQLite: create, insert, query strikes
│   └── utils.py         # haversine(), decode_lzw(), compute_eta()
├── services/
│   ├── blitzortung.py   # WebSocket client → parse → add_strike()
│   ├── cluster_tracker.py   # HDBSCAN loop, Kalman filter, WLS velocity
│   └── connection_manager.py  # broadcast() to all open browser WebSockets
├── models/schemas.py    # Pydantic response models
└── api/routes.py        # REST + WebSocket endpoints

frontend/src/
├── App.jsx              # State, WebSocket, derives displayStrikes/dashboardStrikes
├── constants.js         # Shared thresholds (MIN_CLUSTER_STRIKES etc.)
└── components/
    ├── StrikeMap.jsx    # Leaflet imperative layer management
    ├── Dashboard.jsx    # Pure display — receives strikes/clusters as props
    ├── SettingsPanel.jsx
    └── TimeSlider.jsx
```

## Backend

### Linting

```bash
cd backend
ruff check app/       # 0 errors expected
ruff format app/      # auto-format
```

Configured in `backend/ruff.toml`: `line-length = 100`, rules `E F W I`.

### Clustering pipeline

1. `blitzortung.py` calls `cluster_manager.add_strike(lat, lon, country)` for every received strike.
2. `ClusterManager.add_strike()` filters to `max(2 × OBS_RADIUS_KM, 1500 km)` around the target, then appends to `_strike_buf`.
3. `_hdbscan_loop()` (asyncio task, 60 s interval) calls `_run_hdbscan()`:
   - Builds a coordinate array from strikes within the last 20 minutes.
   - Runs `HDBSCAN(min_cluster_size=50, min_samples=10, metric='haversine')` in a thread-pool executor.
   - Discards labels whose 2-sigma ellipse major axis exceeds 500 km (bridging artifact).
   - Calls `_reconcile()` to match new labels to existing `Cluster` objects (nearest centroid ≤ 150 km).
4. Clusters older than 15 minutes without a feed are expired.
5. On each HDBSCAN run, the broadcast callback registered in `main.py` fires for all changed/removed clusters.

### Kalman filter

Each `Cluster` holds `_kf_x` (2×1 position) and `_kf_P` (2×2 covariance). Every time HDBSCAN produces a new centroid for that cluster, `feed()` runs one KF predict+update step:

```
F = I, H = I, R = 2.0·I, Q = dt·0.01·I
```

Once ≥ 8 centroid snapshots exist (≈ 8 minutes), WLS over the last 6 gives speed and bearing.

### Adding a new API endpoint

1. Add a function to `backend/app/api/routes.py` decorated with `@router.get(...)` or `@router.post(...)`.
2. If it needs `ClusterManager` or `Database`, import the module-level singletons from `routes.py` (they are injected in `main.py` via `routes.set_managers(...)`).
3. Run `ruff check app/` before committing.

## Frontend

### Linting

```bash
cd frontend
$(conda run -n lightning-radar which node) node_modules/.bin/eslint src/
```

Expected: 0 errors, 0 warnings.

### State flow

```
App.jsx
  │  WebSocket messages → setState
  ├─ displayStrikes  ──→ StrikeMap (map view, time-windowed)
  ├─ dashboardStrikes ─→ Dashboard (stats, always live)
  ├─ clusters        ──→ StrikeMap + Dashboard
  └─ settings        ──→ all components
```

`StrikeMap` uses Leaflet imperatively (not React-rendered DOM). Layer rebuilds are
triggered by `useEffect` watching specific deps; strike markers use a 2-second
`setInterval` instead of per-strike effects to avoid 5–10 renders/second.

### Adding a component

1. Create `frontend/src/components/MyComponent.jsx`.
2. Import it in the file that owns its data (usually `App.jsx`).
3. Pass data down as props; keep components stateless where possible.
4. Add a corresponding `MyComponent.css` if it needs non-trivial styles.

### Vite proxy

`frontend/vite.config.js` proxies `/api` and `/ws` to `http://localhost:8000`
during development, so the frontend can call `/api/settings` without CORS issues.
In production the backend serves the built frontend directly and no proxy is needed.

## Committing

Group commits by concern:

| Concern | Example message |
|---|---|
| Backend feature | `feat(clustering): switch to HDBSCAN periodic re-clustering` |
| Frontend feature | `feat(map): render clusters as covariance ellipses` |
| Bug fix | `fix(tracker): discard spurious clusters wider than 500 km` |
| Housekeeping | `chore: lint cleanup, remove stale docs` |

Use conventional commits format (`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`).

## Troubleshooting

**Backend won't start — `ModuleNotFoundError: No module named 'sklearn'`**

```bash
conda activate lightning-radar
pip install scikit-learn
```

**Blitzortung feed silent after a few minutes**

The Blitzortung server closes idle connections. `blitzortung.py` reconnects
automatically with exponential backoff; watch backend logs for `[Blitzortung] reconnecting`.

**Too many small clusters appearing**

Check `MIN_CLUSTER_SIZE` and `MIN_SAMPLES` in `cluster_tracker.py`. Raising
`MIN_CLUSTER_SIZE` reduces the number of clusters. The geographic pre-filter
(`max(2×OBS_RADIUS_KM, 1500 km)`) prevents global data from polluting the view;
check that `OBS_RADIUS_KM` is set sensibly for your target.

**ESLint `node` not found**

Node is installed inside the conda environment:

```bash
$(conda run -n lightning-radar which node) node_modules/.bin/eslint src/
```

**Frontend build fails**

```bash
cd frontend
rm -rf node_modules .vite
npm install
npm run build
```
