import React, { useState } from 'react';
import { startLoad, stopLoad } from './api';

// Drives the SIMULATED load generator on the backend.
export default function LoadPanel() {
  const [users, setUsers] = useState(200);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onStart() {
    setBusy(true);
    try {
      await startLoad(Number(users), 1.5, 0);
      setRunning(true);
    } finally {
      setBusy(false);
    }
  }
  async function onStop() {
    setBusy(true);
    try {
      await stopLoad();
      setRunning(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel load-panel">
      <div className="panel-head">
        <h3>Load generator</h3>
        <span className="sim-badge">SIMULATED</span>
      </div>
      <div className="load-controls">
        <label className="slider-label">
          {users} simulated users
          <input
            type="range"
            min="10"
            max="500"
            step="10"
            value={users}
            onChange={e => setUsers(e.target.value)}
            disabled={running}
          />
        </label>
        {running ? (
          <button className="btn btn-stop" disabled={busy} onClick={onStop}>Stop load</button>
        ) : (
          <button className="btn btn-go" disabled={busy} onClick={onStart}>Run load test</button>
        )}
      </div>
      <p className="hint">
        Each simulated user loops watchlist refreshes through the full Mendr path. Traffic
        is budget-safe (the shim serves a cached upstream payload), and every figure is
        labelled SIMULATED - never a claim of real users.
      </p>
    </section>
  );
}
