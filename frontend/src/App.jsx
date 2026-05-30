import { useEffect, useState, useRef, useMemo, useCallback } from 'react';
import './App.css';
import Dashboard from './components/Dashboard';
import StrikeMap from './components/StrikeMap';
import SettingsPanel from './components/SettingsPanel';
import TimeSlider from './components/TimeSlider';

const LIVE_WINDOW_MS = 30 * 60 * 1000;

// Module-level sequence so every strike gets a unique React key even when
// time_ms + lat + lon are identical (same physical strike, multiple sensors).
let _seq = 0;
const stampStrike = (s) => ({ ...s, _key: `${s.time_ms}_${s.lat}_${s.lon}_${_seq++}` });

function App() {
  const [strikes, setStrikes]             = useState([]);
  const [clusters, setClusters]           = useState([]);
  const [dbTotal, setDbTotal]             = useState(0);
  const [settings, setSettings]           = useState({
    target_name: 'Vienna', target_lat: 48.21, target_lon: 16.37,
    alert_radius_km: 50, obs_radius_km: 1000,
  });
  const [connectionStatus, setConnectionStatus] = useState('connecting');
  const [showSettings, setShowSettings]   = useState(false);
  const [isLive, setIsLive]               = useState(true);
  const [minutesAgo, setMinutesAgo]       = useState(0);
  const [historyStrikes, setHistoryStrikes] = useState([]);
  const [selectedStrike, setSelectedStrike] = useState(null);
  const [selectedCluster, setSelectedCluster] = useState(null);
  const [mapMode, setMapMode] = useState('points');

  const wsRef               = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef   = useRef(null);
  const sliderDebounceRef   = useRef(null);
  // Incremented on every intentional close so stale onclose handlers
  // (from React StrictMode double-mount) don't schedule spurious reconnects.
  const connIdRef           = useRef(0);

  // ── history ──────────────────────────────────────────────────────────────
  const fetchHistory = useCallback(async (minsAgo) => {
    const toMs   = Date.now() - minsAgo * 60_000;
    const fromMs = toMs - LIVE_WINDOW_MS;
    try {
      const resp = await fetch(
        `/api/strikes/history?from_ms=${fromMs}&to_ms=${toMs}&limit=2000`
      );
      const data = await resp.json();
      setHistoryStrikes(data.strikes.map(stampStrike));
    } catch (e) {
      console.error('History fetch failed:', e);
    }
  }, []);

  const handleSliderChange = useCallback((mins) => {
    setMinutesAgo(mins);
    if (mins === 0) {
      setIsLive(true);
      setHistoryStrikes([]);
    } else {
      setIsLive(false);
      clearTimeout(sliderDebounceRef.current);
      sliderDebounceRef.current = setTimeout(() => fetchHistory(mins), 300);
    }
  }, [fetchHistory]);

  const handleLiveToggle = useCallback(() => {
    if (isLive) {
      setIsLive(false); setMinutesAgo(5); fetchHistory(5);
    } else {
      setIsLive(true); setMinutesAgo(0); setHistoryStrikes([]);
    }
  }, [isLive, fetchHistory]);

  // ── derived strike lists ─────────────────────────────────────────────────
  // Map: time-windowed view (last 30 min live, or historical window)
  const displayStrikes = useMemo(() => {
    if (!isLive) return historyStrikes;
    const cutoff = Date.now() - LIVE_WINDOW_MS;
    return strikes.filter(s => s.time_ms >= cutoff);
  }, [isLive, strikes, historyStrikes]);

  // Dashboard: full live stream so stats + Recent Strikes always update
  const dashboardStrikes = useMemo(
    () => isLive ? strikes : historyStrikes,
    [isLive, strikes, historyStrikes]
  );

  // ── WebSocket ────────────────────────────────────────────────────────────
  const handleMessage = useCallback((event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'init') {
        if (msg.total_strikes) setDbTotal(msg.total_strikes);
        if (msg.settings)      setSettings(msg.settings);
        if (msg.recent_strikes) setStrikes(msg.recent_strikes.map(stampStrike));
        if (msg.clusters)      setClusters(msg.clusters);
      } else if (msg.type === 'strike') {
        if (msg.db_total) setDbTotal(msg.db_total);
        const strike = stampStrike(msg);
        setStrikes(prev => {
          const cutoff = Date.now() - LIVE_WINDOW_MS - 60_000;
          return [...prev.filter(s => s.time_ms >= cutoff), strike];
        });
      } else if (msg.type === 'cluster') {
        setClusters(prev => [...prev.filter(c => c.id !== msg.id), msg]);
      } else if (msg.type === 'cluster_removed') {
        setClusters(prev => prev.filter(c => c.id !== msg.id));
      } else if (msg.type === 'settings_updated') {
        setSettings(prev => ({ ...prev, ...msg }));
      }
    } catch (err) {
      console.error('WS parse error:', err);
    }
  }, []);

  const connectWebSocket = useCallback(() => {
    // Tag this connection; if connIdRef changes before onclose fires the
    // handler is stale and must not schedule a reconnect.
    const myId = connIdRef.current;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

    ws.onopen = () => {
      if (connIdRef.current !== myId) { ws.close(); return; }
      setConnectionStatus('connected');
      reconnectAttemptRef.current = 0;
    };

    ws.onmessage = handleMessage;
    ws.onerror   = () => { if (connIdRef.current === myId) setConnectionStatus('error'); };

    ws.onclose = () => {
      if (connIdRef.current !== myId) return; // stale — cleanup already ran
      setConnectionStatus('reconnecting');
      const delay = Math.min(1000 * 2 ** reconnectAttemptRef.current, 30_000);
      reconnectAttemptRef.current++;
      reconnectTimerRef.current = setTimeout(connectWebSocket, delay);
    };

    wsRef.current = ws;
  }, [handleMessage]);

  useEffect(() => {
    fetch('/api/settings').then(r => r.json()).then(setSettings).catch(console.error);
    connectWebSocket();
    return () => {
      connIdRef.current++;
      clearTimeout(reconnectTimerRef.current);
      clearTimeout(sliderDebounceRef.current);
      wsRef.current?.close();
    };
  }, [connectWebSocket]);

  // ── stats ─────────────────────────────────────────────────────────────────
  const stats = useMemo(() => ({
    total_strikes: dbTotal,
  }), [dbTotal]);

  return (
    <div className="app-container">
      <div className="map-wrapper">
        <StrikeMap
          strikes={displayStrikes}
          clusters={clusters}
          settings={settings}
          selectedStrike={selectedStrike}
          onPinDone={() => setSelectedStrike(null)}
          mapMode={mapMode}
          onStrikeSelect={setSelectedStrike}
          selectedCluster={selectedCluster}
          onClusterSelect={setSelectedCluster}
        />
        <TimeSlider
          isLive={isLive}
          minutesAgo={minutesAgo}
          onChange={handleSliderChange}
          onLiveToggle={handleLiveToggle}
          mapMode={mapMode}
          onMapModeChange={setMapMode}
        />
      </div>
      <Dashboard
        strikes={dashboardStrikes}
        clusters={clusters}
        settings={settings}
        stats={stats}
        connectionStatus={connectionStatus}
        onOpenSettings={() => setShowSettings(true)}
        onStrikeSelect={setSelectedStrike}
        selectedCluster={selectedCluster}
        onClusterSelect={setSelectedCluster}
      />
      {showSettings && (
        <SettingsPanel
          settings={settings}
          onSave={s => setSettings(s)}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}

export default App;
