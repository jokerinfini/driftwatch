import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getAlerts, getCoin, getWatchlist } from './api';
import MetricsPanel from './MetricsPanel';
import DriftSwitch from './DriftSwitch';
import LoadPanel from './LoadPanel';
import Watchlist from './Watchlist';
import CoinHealthCard from './CoinHealthCard';

const FEATURED = 'bitcoin';
const POLL_MS = 4000;

export default function App() {
  const [watch, setWatch] = useState(null);
  const [coin, setCoin] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState(null);
  const timer = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const [w, c, a] = await Promise.all([
        getWatchlist(),
        getCoin(FEATURED),
        getAlerts().catch(() => ({ alerts: [] })),
      ]);
      setWatch(w);
      setCoin(c);
      setAlerts(a.alerts || []);
      setError(null);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Backend unreachable');
    }
  }, []);

  useEffect(() => {
    refresh();
    timer.current = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer.current);
  }, [refresh]);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>DriftWatch</h1>
          <p className="tagline">
            A live crypto watchlist that never breaks when CoinGecko changes its schema —
            healed live by <strong>Mendr</strong>.
          </p>
        </div>
        <div className="mode-chip">
          {watch?.meta?.mode ? `gateway: ${watch.meta.mode === 'real' ? 'Mendr edge' : 'emulated Mendr'}` : ''}
        </div>
      </header>

      {error && <div className="notice notice-error">{error}</div>}

      <MetricsPanel />

      <div className="two-col">
        <DriftSwitch onChange={refresh} />
        <LoadPanel />
      </div>

      <Watchlist data={watch} />

      <CoinHealthCard detail={coin} />

      <section className="panel alerts-panel">
        <div className="panel-head"><h3>Price alerts</h3></div>
        {alerts.length === 0 ? (
          <p className="hint">No alerts yet — alerts fire when a coin moves sharply vs its rolling average.</p>
        ) : (
          <ul className="alerts">
            {alerts.slice(0, 8).map((a, i) => (
              <li key={i} className={a.direction === 'up' ? 'up' : 'down'}>
                <strong>{a.symbol || a.coin}</strong> {a.direction === 'up' ? '▲' : '▼'} {a.move_pct}%
                <span className="alert-price">₹{Number(a.price).toLocaleString('en-IN')}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="footer">
        <span>DriftWatch · demo for Mendr · Data by CoinGecko</span>
        <span className="sim-note">All traffic & user figures are SIMULATED.</span>
      </footer>
    </div>
  );
}
