/**
 * Local Nostradamus server API client (serve.py).
 */

const BASE = '';

export async function apiGet(path) {
  const r = await fetch(`${BASE}${path}`, { cache: 'no-cache' });
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export async function apiPost(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

export function isServerMode() {
  return apiGet('/api/health').then(() => true).catch(() => false);
}

export const api = {
  health: () => apiGet('/api/health'),
  overview: () => apiGet('/api/models/overview'),
  commandCenter: () => apiGet('/api/command-center'),
  alpacaAccount: () => apiGet('/api/alpaca/account'),
  fleet: () => apiGet('/api/fleet'),
  fleetAgent: (id) => apiGet(`/api/fleet/agent/${encodeURIComponent(id)}`),
  walkforward: () => apiGet('/api/walkforward'),
  bridgeTopTraders: (limit = 3) => apiGet(`/api/bridge/top-traders?limit=${limit}`),
  brainInsights: () => apiGet('/api/brain/insights'),
  brainChangelogAppend: (body) => apiPost('/api/brain/changelog', body),
  pipelineHealth: () => apiGet('/api/pipeline/health'),
  livePredictions: (limit = 50) => apiGet(`/api/predictions/live?limit=${limit}`),
  decisions: () => apiGet('/api/decisions'),
  quote: (symbol) => apiGet(`/api/quote?symbol=${encodeURIComponent(symbol)}`),
  news: (symbol, max = 8) => apiGet(`/api/news?symbol=${encodeURIComponent(symbol)}&max_headlines=${max}`),
  bars: (symbol, limit = 90) => apiGet(`/api/bars?symbol=${encodeURIComponent(symbol)}&limit=${limit}`),
  reasoningStrategy: () => apiGet('/api/reasoning/strategy'),
  reasoningJournal: (limit = 20) => apiGet(`/api/reasoning/journal?limit=${limit}`),
  swingManifest: () => apiGet('/api/trading/manifest'),
  daytradeManifest: () => apiGet('/api/daytrade/manifest'),
  brainSchedule: () => apiGet('/api/brain/schedule'),
  congressNotable: () => apiGet('/api/congress/notable'),
  predictionMarkets: () => apiGet('/api/prediction-markets'),
  pennyOverview: () => apiGet('/api/penny/overview'),
  pennyTick: () => apiPost('/api/penny/tick', {}),
  arenaExperiment: () => apiGet('/api/arena/experiment'),
  arenaCompare: () => apiGet('/api/arena/compare'),
  arenaTraders: (version) => apiGet(`/api/arena/${version}/traders`),
  arenaTrader: (version, id) => apiGet(`/api/arena/${version}/trader/${id}`),
  arenaPulse: () => apiPost('/api/arena/pulse', {}),
  arenaOperating: () => apiGet('/api/arena/operating'),
  realAgents: () => apiGet('/api/real-agents'),
  stackOverview: () => apiGet('/api/stack/overview'),
  ultimateModel: () => apiGet('/api/ultimate-model'),
  megamind: () => apiGet('/api/megamind'),
  megamindTick: () => apiPost('/api/megamind/tick', {}),
  megamindApprove: (id) => apiPost(`/api/megamind/recommendations/${id}/approve`, {}),
  megamindReject: (id) => apiPost(`/api/megamind/recommendations/${id}/reject`, {}),
  megamindImplemented: (id) => apiPost(`/api/megamind/recommendations/${id}/implemented`, {}),
  retrain: () => apiPost('/api/retrain', {}),
  retrainStatus: () => apiGet('/api/retrain/status'),
};
