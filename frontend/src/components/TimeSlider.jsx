import React from 'react';
import './TimeSlider.css';

function TimeSlider({ isLive, minutesAgo, onChange, onLiveToggle, mapMode, onMapModeChange }) {
  const formatTime = (m) => {
    if (m === 0) return 'Now';
    const h = Math.floor(m / 60);
    const min = m % 60;
    if (h > 0 && min > 0) return `-${h}h ${min}m`;
    if (h > 0) return `-${h}h`;
    return `-${min}m`;
  };

  // Slider: left = 3h ago (value=0), right = now (value=180)
  const sliderValue = 180 - minutesAgo;

  return (
    <div className="time-slider-bar">
      <button
        className={`live-btn${isLive ? ' live-on' : ''}`}
        onClick={onLiveToggle}
        title={isLive ? 'Live mode — click to pause' : 'Click to resume live'}
      >
        ◉ LIVE
      </button>
      <div className="slider-track">
        <span className="slider-edge-label">-3h</span>
        <input
          type="range"
          min={0}
          max={180}
          step={5}
          value={sliderValue}
          onChange={e => onChange(180 - Number(e.target.value))}
          className="time-range-input"
        />
        <span className="slider-edge-label">Now</span>
      </div>
      <span className="time-label">{formatTime(minutesAgo)}</span>
      <div className="mode-toggle">
        <div className="mode-toggle-track">
          <button
            className={`mode-btn${mapMode === 'points' ? ' mode-btn-active' : ''}`}
            onClick={() => onMapModeChange('points')}
            title="Show individual strike points"
          >
            ⚡ Points
          </button>
          <button
            className={`mode-btn${mapMode === 'cluster' ? ' mode-btn-active' : ''}`}
            onClick={() => onMapModeChange('cluster')}
            title="Show storm clusters only"
          >
            ⛈ Cluster
          </button>
        </div>
      </div>
    </div>
  );
}

export default TimeSlider;
