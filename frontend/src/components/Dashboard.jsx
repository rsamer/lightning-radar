import { useMemo, useState, useRef } from 'react';
import ReactDOM from 'react-dom';
import './Dashboard.css';
import { MIN_CLUSTER_STRIKES } from '../constants';

// Browser-native country name lookup — no data table needed
const regionNames = new Intl.DisplayNames(['en'], { type: 'region' });

const getCountryName = (code) => {
  if (!code || code.length !== 2) return code || 'Unknown';
  try { return regionNames.of(code.toUpperCase()); } catch { return code; }
};

const getFlag = (code) => {
  if (!code || code.length !== 2) return null;
  return [...code.toUpperCase()].map(c =>
    String.fromCodePoint(0x1F1E6 + c.charCodeAt(0) - 65)
  ).join('');
};

// Returns a Unicode arrow character closest to the given bearing (clockwise from north)
function bearingArrow(deg) {
  const arrows = ['↑','↗','→','↘','↓','↙','←','↖'];
  return arrows[Math.round(((deg % 360) + 360) % 360 / 45) % 8];
}

function Dashboard({ strikes, clusters, settings, stats, connectionStatus, onOpenSettings, onStrikeSelect, selectedCluster, onClusterSelect }) {
  const [recentStrikesCount, setRecentStrikesCount] = useState(10);
  const [tooltipRect, setTooltipRect] = useState(null);
  const threatRef = useRef(null);

  // Recompute distance on the frontend so target changes (e.g. Vienna→Zurich) take
  // effect immediately without waiting for the backend to rebroadcast cluster states.
  const nearbyClusters = useMemo(() => {
    const { target_lat, target_lon, obs_radius_km } = settings;
    return clusters.filter(c => {
      if (c.strike_count < MIN_CLUSTER_STRIKES) return false;
      const dLat = (c.lat - target_lat) * Math.PI / 180;
      const dLon = (c.lon - target_lon) * Math.PI / 180;
      const a = Math.sin(dLat / 2) ** 2 +
        Math.cos(target_lat * Math.PI / 180) * Math.cos(c.lat * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
      const distKm = 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
      return distKm <= obs_radius_km;
    });
  }, [clusters, settings]);

  const strikeStats = useMemo(() => {
    const now = Date.now();
    return {
      strikes5min:  strikes.filter(s => now - s.time_ms <  5 * 60_000).length,
      strikes15min: strikes.filter(s => now - s.time_ms < 15 * 60_000).length,
      clusterCount: clusters.length,
      nearbyCount: nearbyClusters.length,
    };
  }, [strikes, clusters, nearbyClusters]);

  // Top-5 countries — SEA excluded (it's an ocean tag, not a country)
  const topCountries = useMemo(() => {
    const counts = {};
    strikes.forEach(s => {
      const c = s.country;
      if (!c || c === 'SEA' || c.length !== 2) return;
      counts[c] = (counts[c] || 0) + 1;
    });
    return Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([code, count]) => ({ code, count, flag: getFlag(code), name: getCountryName(code) }));
  }, [strikes]);

  const threatLevel = useMemo(() => {
    if (!nearbyClusters.length) return { level: 'LOW', cls: 'threat-low' };
    const maxNearby = Math.max(...nearbyClusters.map(c => c.strike_count || 1));
    const hasEta    = nearbyClusters.some(c => c.eta_hours != null);
    const imminentEta = nearbyClusters.some(c => c.eta_hours != null && c.eta_hours < 1);
    if (imminentEta || maxNearby > 100) return { level: 'CRITICAL', cls: 'threat-critical' };
    if (hasEta      || maxNearby > 50)  return { level: 'HIGH',     cls: 'threat-high' };
    if (nearbyClusters.length > 2 || maxNearby > 20) return { level: 'MODERATE', cls: 'threat-moderate' };
    return { level: 'LOW', cls: 'threat-low' };
  }, [nearbyClusters]);

  const threatTooltip = useMemo(() => {
    const now = Date.now();
    const rate5min = strikes.filter(s => now - s.time_ms < 5 * 60_000).length;
    const approaching = nearbyClusters
      .filter(c => c.eta_hours != null)
      .sort((a, b) => a.eta_hours - b.eta_hours);
    const nearest = nearbyClusters.length
      ? nearbyClusters.reduce((m, c) => c.dist_to_target_km < m.dist_to_target_km ? c : m)
      : null;
    return { rate5min, approaching, nearest };
  }, [strikes, nearbyClusters]);

  const statusCls = connectionStatus === 'connected'   ? 'pill-connected'
                  : connectionStatus === 'reconnecting' ? 'pill-warn'
                  : connectionStatus === 'connecting'   ? 'pill-warn'
                  : 'pill-error';

  const recentStrikes = strikes.slice(-recentStrikesCount).reverse();

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <span className="header-title">Lightning Radar</span>
        <div className="header-right">
          <span className={`conn-pill ${statusCls}`}>{connectionStatus}</span>
          <button className="settings-btn" onClick={onOpenSettings} title="Settings">&#9881;</button>
        </div>
      </div>

      <div
        ref={threatRef}
        className={`threat-indicator ${threatLevel.cls}`}
        style={{ cursor: 'help' }}
        onMouseEnter={() => {
          const r = threatRef.current?.getBoundingClientRect();
          if (r) setTooltipRect(r);
        }}
        onMouseLeave={() => setTooltipRect(null)}
      >
        <div className="threat-level">{threatLevel.level}</div>
        <div className="threat-text">Threat Level &nbsp;ℹ</div>
      </div>

      {tooltipRect && ReactDOM.createPortal(
        <div className="threat-tooltip" style={{
          position: 'fixed',
          top:   tooltipRect.bottom + 8,
          left:  tooltipRect.left,
          width: tooltipRect.width,
          zIndex: 9999,
        }}>
          <div className="threat-tooltip-title">
            {threatLevel.level === 'CRITICAL' ? '🔴' :
             threatLevel.level === 'HIGH'     ? '🟠' :
             threatLevel.level === 'MODERATE' ? '🟡' : '🟢'}
            &nbsp;{threatLevel.level} — situation summary
          </div>
          <div className="threat-tooltip-row">
            ⚡ <strong>{threatTooltip.rate5min}</strong> strikes in last 5 min
          </div>
          {clusters.length > 0 && (
            <div className="threat-tooltip-row">
              🌩️ <strong>{clusters.length}</strong> active storm clusters globally
            </div>
          )}
          {nearbyClusters.length > 0 ? (
            <div className="threat-tooltip-row">
              📍 <strong>{nearbyClusters.length}</strong> cluster{nearbyClusters.length > 1 ? 's' : ''} within {settings.obs_radius_km} km
            </div>
          ) : (
            <div className="threat-tooltip-row">✅ No clusters within {settings.obs_radius_km} km</div>
          )}
          {threatTooltip.nearest && (
            <div className="threat-tooltip-row">
              🎯 Nearest: <strong>{Math.round(threatTooltip.nearest.dist_to_target_km)} km</strong> away
              {threatTooltip.nearest.speed_kmh > 5 && (
                <span> · {Math.round(threatTooltip.nearest.speed_kmh)} km/h</span>
              )}
            </div>
          )}
          {threatTooltip.approaching.length > 0 ? (
            <div className="threat-tooltip-row threat-tooltip-warn">
              ⚠️ <strong>{threatTooltip.approaching.length}</strong> approaching — ETA&nbsp;
              <strong>{threatTooltip.approaching[0].eta_hours.toFixed(1)} h</strong>
            </div>
          ) : nearbyClusters.length > 0 ? (
            <div className="threat-tooltip-row">↪ No clusters currently on approach</div>
          ) : null}
          {threatLevel.level === 'CRITICAL' && (
            <div className="threat-tooltip-row threat-tooltip-warn">⛈️ Severe — seek shelter if outdoors</div>
          )}
          {threatLevel.level === 'LOW' && !nearbyClusters.length && (
            <div className="threat-tooltip-row">🌤️ Activity distant — no immediate risk</div>
          )}
        </div>,
        document.body
      )}

      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-label">Total Strikes</div>
          <div className="stat-value">{stats.total_strikes.toLocaleString()}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Last 5 min</div>
          <div className="stat-value">{strikeStats.strikes5min}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Last 15 min</div>
          <div className="stat-value">{strikeStats.strikes15min}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Clusters (global / nearby)</div>
          <div className="stat-value">{strikeStats.clusterCount} / {strikeStats.nearbyCount}</div>
        </div>
      </div>

      {topCountries.length > 0 && (
        <>
          <div className="section-title">Top 5 Countries (live)</div>
          <div className="top-countries">
            {topCountries.map((c, i) => (
              <div key={c.code} className="top-country-row" title={c.name}>
                <span className="rank">#{i + 1}</span>
                <span className="country-flag">{c.flag}</span>
                <span className="country-code">{c.code}</span>
                <div className="country-bar-wrap">
                  <div
                    className="country-bar"
                    style={{ width: `${(c.count / (topCountries[0]?.count || 1)) * 100}%` }}
                  />
                </div>
                <span className="country-count">{c.count}</span>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="section-title">Nearby Storm Clusters ({settings.obs_radius_km} km)</div>
      {nearbyClusters.length > 0 ? (
        <div className="clusters-list">
          {nearbyClusters.slice(-5).reverse().map(cluster => {
            const isSelected = selectedCluster?.id === cluster.id;
            return (
              <div
                key={cluster.id}
                className={`cluster-item cluster-item-clickable${isSelected ? ' cluster-item-selected' : ''}`}
                onClick={() => onClusterSelect?.(isSelected ? null : cluster)}
                title="Click to locate on map"
              >
                <div className="cluster-header">
                  <span className="cluster-id">Cluster #{cluster.id}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    {cluster.country && cluster.country.length === 2 && (
                      <span className="cluster-country" title={getCountryName(cluster.country)}>
                        {getFlag(cluster.country)}
                        <span className="cluster-country-code">{cluster.country}</span>
                      </span>
                    )}
                    <span
                      className="cluster-severity"
                      style={{ color: cluster.strike_count > 50 ? '#ef4444' : cluster.strike_count > 20 ? '#f59e0b' : '#22c55e' }}
                    >
                      &#9888; {cluster.strike_count}
                    </span>
                  </div>
                </div>
                <div className="cluster-details">
                  <div>Pos: {cluster.lat.toFixed(3)}&deg;, {cluster.lon.toFixed(3)}&deg;</div>
                  <div>
                    Speed: {cluster.speed_kmh != null ? `${cluster.speed_kmh.toFixed(1)} km/h` : 'N/A'}
                    {cluster.bearing_deg != null && cluster.speed_kmh > 1 && (
                      <span style={{ marginLeft: 4, color: '#94a3b8' }}>
                        &nbsp;{bearingArrow(cluster.bearing_deg)}
                      </span>
                    )}
                  </div>
                  {cluster.eta_hours != null && (
                    <div style={{ color: cluster.eta_hours < 1 ? '#ef4444' : '#f59e0b' }}>
                      ETA: {cluster.eta_hours.toFixed(2)} h
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="no-data">No storm clusters within {settings.obs_radius_km} km</p>
      )}

      <div className="section-title">Recent Strikes</div>
      <div className="controls">
        <label>Show:</label>
        <select value={recentStrikesCount} onChange={e => setRecentStrikesCount(Number(e.target.value))}>
          <option value={5}>Last 5</option>
          <option value={10}>Last 10</option>
          <option value={20}>Last 20</option>
          <option value={50}>Last 50</option>
        </select>
      </div>

      {recentStrikes.length > 0 ? (
        <div className="strikes-list">
          <div className="strikes-table-header">
            <span>Time</span>
            <span>Lat, Lon</span>
            <span>Flag</span>
          </div>
          {recentStrikes.map(strike => (
            <div
              key={strike._key}
              className="strike-item strike-item-clickable"
              onClick={() => onStrikeSelect?.(strike)}
              title="Click to locate on map"
            >
              <div className="strike-time">{new Date(strike.time_ms).toLocaleTimeString()}</div>
              <div className="strike-coords">
                {strike.lat.toFixed(3)}&deg;, {strike.lon.toFixed(3)}&deg;
              </div>
              <div
                className="strike-flag"
                title={strike.country ? getCountryName(strike.country) : 'Ocean / Sea'}
              >
                {strike.country && strike.country !== 'SEA'
                  ? getFlag(strike.country)
                  : '🌊'}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="no-data">No strikes detected</p>
      )}

      <div className="dashboard-footer">
        <small>{settings.target_name} &mdash; Alert radius: {settings.alert_radius_km} km</small>
        <small>
          Data: <a href="https://www.blitzortung.org/" target="_blank" rel="noreferrer">Blitzortung.org</a> &amp; contributors
        </small>
      </div>
    </div>
  );
}

export default Dashboard;
