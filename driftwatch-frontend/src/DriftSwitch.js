import React, { useEffect, useState } from 'react';
import { getDrift, setDrift } from './api';

// Each scenario maps to a real, documented CoinGecko breaking change.
const SCENARIOS = [
  { id: 'community_removed', label: 'community_data + developer_data removed', date: '2026-08-28' },
  { id: 'trust_score_null', label: 'ticker trust_score -> null', date: '2026-03-03' },
  { id: 'twitter_removed', label: 'twitter_followers removed', date: '2025-05-15' },
  { id: 'rehypothecation', label: 'market_cap_rank -> null (rehypothecated)', date: '2026-02-04' },
  { id: 'rename_price', label: 'current_price field renamed', date: 'generic' },
  { id: 'vef_removed', label: 'VEF currency deprecated (price null)', date: '2026-06-30' },
];

export default function DriftSwitch({ onChange }) {
  const [enabled, setEnabled] = useState([]);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try { setEnabled((await getDrift()).enabled || []); } catch { /* shim offline */ }
  };
  useEffect(() => { refresh(); }, []);

  async function toggle(scenario, on) {
    setBusy(true);
    try {
      const res = await setDrift(scenario, on);
      setEnabled(res.enabled || []);
      onChange && onChange();
    } finally {
      setBusy(false);
    }
  }

  const anyOn = enabled.length > 0;

  return (
    <section className="panel drift-panel">
      <div className="panel-head">
        <h3>Drift switch</h3>
        <button
          className={`big-toggle ${anyOn ? 'on' : ''}`}
          disabled={busy}
          onClick={() => toggle('all', !anyOn)}
          title="Flip every documented CoinGecko drift at once"
        >
          {anyOn ? 'Heal all (Mendr)' : 'Break everything'}
        </button>
      </div>
      <p className="hint">
        Flip the upstream into a real, documented CoinGecko drift. Mendr heals it back to
        the contract, so the app keeps working with zero code change.
      </p>
      <ul className="scenario-list">
        {SCENARIOS.map(s => {
          const on = enabled.includes(s.id);
          return (
            <li key={s.id} className={on ? 'scenario on' : 'scenario'}>
              <label>
                <input
                  type="checkbox"
                  checked={on}
                  disabled={busy}
                  onChange={e => toggle(s.id, e.target.checked)}
                />
                <span className="scenario-label">{s.label}</span>
                <span className="scenario-date">{s.date}</span>
              </label>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
