import { useState } from 'react';
import './SettingsPanel.css';

function SettingsPanel({ settings, onSave, onClose }) {
  const [form, setForm] = useState({
    target_name: settings.target_name,
    target_lat: settings.target_lat,
    target_lon: settings.target_lon,
    alert_radius_km: settings.alert_radius_km,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;
    setForm(prev => ({
      ...prev,
      [name]: name === 'target_name' ? value : parseFloat(value) || value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const updated = await res.json();
      onSave(updated);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-overlay" onClick={onClose}>
      <div className="settings-panel" onClick={e => e.stopPropagation()}>
        <div className="settings-header">
          <h2>Settings</h2>
          <button className="close-btn" onClick={onClose}>×</button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="settings-section">
            <h3>Target Location</h3>
            <p className="settings-hint">Alerts and distance calculations are relative to this point.</p>

            <label>
              Name
              <input
                type="text"
                name="target_name"
                value={form.target_name}
                onChange={handleChange}
                placeholder="e.g. Vienna"
              />
            </label>
            <label>
              Latitude
              <input
                type="number"
                name="target_lat"
                value={form.target_lat}
                onChange={handleChange}
                step="0.001"
                min="-90"
                max="90"
              />
            </label>
            <label>
              Longitude
              <input
                type="number"
                name="target_lon"
                value={form.target_lon}
                onChange={handleChange}
                step="0.001"
                min="-180"
                max="180"
              />
            </label>
          </div>

          <div className="settings-section">
            <h3>Alert Radius</h3>
            <label>
              Radius (km)
              <input
                type="number"
                name="alert_radius_km"
                value={form.alert_radius_km}
                onChange={handleChange}
                step="5"
                min="1"
                max="5000"
              />
            </label>
          </div>

          {error && <p className="settings-error">{error}</p>}

          <div className="settings-actions">
            <button type="button" onClick={onClose}>Cancel</button>
            <button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default SettingsPanel;
