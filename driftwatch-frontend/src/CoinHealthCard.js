import React from 'react';

const num = v => (v == null ? null : Number(v).toLocaleString('en-IN'));

function Stat({ label, value }) {
  return (
    <div className="hc-stat">
      <div className="hc-stat-value">
        {value == null ? <span className="broken">removed</span> : value}
      </div>
      <div className="hc-stat-label">{label}</div>
    </div>
  );
}

function trustClass(t) {
  if (t === 'green') return 'trust trust-green';
  if (t === 'yellow') return 'trust trust-yellow';
  if (t === 'red') return 'trust trust-red';
  return 'trust trust-null';
}

function Card({ title, subtitle, coin, broken }) {
  return (
    <div className={`health-card ${broken ? 'hc-broken' : 'hc-ok'}`}>
      <div className="hc-head">
        <div>
          <h4>{title}</h4>
          <span className="wl-sub">{subtitle}</span>
        </div>
        <span className={trustClass(coin.trust_score)}>
          {coin.trust_score ? `trust: ${coin.trust_score}` : 'trust: null'}
        </span>
      </div>
      <div className="hc-grid">
        <Stat label="reddit subs" value={num(coin.reddit_subscribers)} />
        <Stat label="twitter" value={num(coin.twitter_followers)} />
        <Stat label="github stars" value={num(coin.stars)} />
        <Stat label="forks" value={num(coin.forks)} />
      </div>
    </div>
  );
}

// Featured coin "project health" card - the drift-rich view (community/dev/trust).
export default function CoinHealthCard({ detail }) {
  if (!detail) return null;
  const { coin, naive, meta = {} } = detail;
  const drift = meta.drift;

  return (
    <section className="panel coin-health">
      <div className="panel-head">
        <h3>{coin.name} project health</h3>
        <span className="attribution">{meta.attribution || 'Data by CoinGecko'}</span>
      </div>
      <div className="hc-compare">
        <Card title="Without Mendr" subtitle="raw upstream" coin={naive} broken={drift} />
        <Card title="With Mendr" subtitle="healed to contract" coin={coin} broken={false} />
      </div>
    </section>
  );
}
