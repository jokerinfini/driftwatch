import React from 'react';

const inr = v =>
  v == null ? null : '\u20B9' + Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 });

// A single cell: renders the value, or a red "broken" chip when the upstream drift
// removed/nulled it (this is what the app would show WITHOUT Mendr).
function Cell({ value, render }) {
  if (value == null) return <span className="broken">missing</span>;
  return <span>{render ? render(value) : value}</span>;
}

function Table({ title, rows, subtitle, broken }) {
  return (
    <div className={`wl-table ${broken ? 'wl-broken' : 'wl-ok'}`}>
      <div className="wl-table-head">
        <h4>{title}</h4>
        <span className="wl-sub">{subtitle}</span>
      </div>
      <table>
        <thead>
          <tr><th>Coin</th><th>Price</th><th>Rank</th><th>24h</th></tr>
        </thead>
        <tbody>
          {rows.map(c => {
            const chg = c.price_change_percentage_24h;
            return (
              <tr key={c.id}>
                <td className="wl-coin">
                  {c.image && <img src={c.image} alt="" onError={e => (e.target.style.display = 'none')} />}
                  <span>{c.symbol}</span>
                </td>
                <td><Cell value={c.current_price} render={inr} /></td>
                <td>
                  <Cell value={c.market_cap_rank} render={r => `#${r}`} />
                </td>
                <td>
                  {chg == null ? (
                    <span className="broken">missing</span>
                  ) : (
                    <span className={chg >= 0 ? 'up' : 'down'}>
                      {chg >= 0 ? '+' : ''}{Number(chg).toFixed(2)}%
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function Watchlist({ data }) {
  if (!data) return <div className="panel"><p>Loading watchlist…</p></div>;
  const { coins = [], naive = [], meta = {} } = data;
  const drift = meta.drift;

  return (
    <section className="panel watchlist">
      <div className="panel-head">
        <h3>Crypto watchlist</h3>
        <span className="attribution">{meta.attribution || 'Data by CoinGecko'}</span>
      </div>

      {drift ? (
        <div className="drift-banner">
          Upstream drift detected: <code>{(meta.problems || []).slice(0, 3).join(', ')}</code>
          {(meta.problems || []).length > 3 ? ' …' : ''} — Mendr healed it back to the contract.
        </div>
      ) : (
        <div className="ok-banner">Upstream healthy — contract satisfied.</div>
      )}

      <div className="wl-compare">
        <Table
          title="Without Mendr"
          subtitle="raw upstream (naive client)"
          rows={naive}
          broken={drift}
        />
        <Table
          title="With Mendr"
          subtitle="healed to contract"
          rows={coins}
          broken={false}
        />
      </div>
    </section>
  );
}
