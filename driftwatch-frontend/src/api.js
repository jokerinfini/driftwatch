import axios from 'axios';

// Backend base URL. Set REACT_APP_API_BASE at build time on Vercel to the hosted
// Render backend origin. Empty keeps calls same-origin (CRA dev proxy -> :8010).
export const API_BASE = (process.env.REACT_APP_API_BASE || '').replace(/\/+$/, '');

// EventSource can't use axios baseURL, so build absolute stream URLs here.
export const streamUrl = path => `${API_BASE}${path}`;

const client = axios.create({ baseURL: API_BASE, timeout: 15000 });

export const getWatchlist = () => client.get('/watchlist').then(r => r.data);
export const getCoin = id => client.get(`/coin/${id}`).then(r => r.data);
export const getAlerts = () => client.get('/alerts').then(r => r.data);

// Drift switch (proxied to the shim, which sits behind Mendr).
export const getDrift = () => client.get('/drift').then(r => r.data);
export const setDrift = (scenario, enabled) =>
  client.post('/drift', { scenario, enabled }).then(r => r.data);

// SIMULATED load generator.
export const startLoad = (users, rps_per_user, duration_s) =>
  client.post('/load/start', { users, rps_per_user, duration_s }).then(r => r.data);
export const stopLoad = () => client.post('/load/stop').then(r => r.data);
