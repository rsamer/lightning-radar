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
│   ├── blitzortung.py   # WebSocket client -> parse -> add_strike()
│   ├── cluster_tracker.py   # HDBSCAN loop, Kalman filter, WLS velocity
│   └── connection_manager.py  # broadcast() to all open browser WebSockets
├── models/schemas.py    # Pydantic response models
└── api/routes.py        # REST + WebSocket endpoints

frontend/src/
├── App.jsx              # State, WebSocket, derives displayStrikes/dashboardStrikes
├── constants.js         # Shared thresholds (MIN_CLUSTER_STRIKES etc.)
└── components/
    ├── StrikeMap.jsx    # Leaflet imperative layer management
    ├── Dashboard.jsx    # Pure display - receives strikes/clusters as props
    ├── SettingsPanel.jsx
    └── TimeSlider.jsx
```
