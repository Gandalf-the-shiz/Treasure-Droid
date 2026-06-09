/**
 * Map arena trader ledger JSON → investor decisions.json shape for shared book UI.
 */

export function arenaTraderToBookData(trader, { version = '', traderId = '' } = {}) {
  const daily = trader.daily || [];
  const initial = Number(trader.portfolioSummary?.startingEquityUsd) || 50_000;
  let equity = initial;
  const equityCurve = [];
  const days = [];

  for (let i = 0; i < daily.length; i++) {
    const d = daily[i];
    const retPct = Number(d.returnPct) || 0;
    const prevEquity = equity;
    equity = Number(d.equityAfter) || equity * (1 + retPct / 100);
    const pnlToday = equity - prevEquity;
    const port = d.portfolio || [];

    const picks = port.map((p, idx) => {
      const w = p.weightPct != null ? Number(p.weightPct) / 100 : 0.1;
      const predRet = p.modelPredRetPct != null ? Number(p.modelPredRetPct) / 100 : 0;
      const proba = p.modelProbaUp != null
        ? Number(p.modelProbaUp)
        : (p.score != null ? Math.min(0.95, Math.max(0.05, 0.5 + Number(p.score) * 0.05)) : 0.55);
      const why = [];
      if (p.unifiedRationale) why.push(String(p.unifiedRationale));
      if (p.rationale && p.rationale !== p.unifiedRationale) why.push(String(p.rationale));
      (d.trades || []).filter((t) => t.symbol === p.symbol).forEach((t) => {
        if (t.rationale) why.push(String(t.rationale));
      });
      return {
        rank: idx + 1,
        symbol: p.symbol || '—',
        sector: p.sector || trader.family || '—',
        weight: w,
        notional: Number(p.notionalUsd) || 0,
        pred_proba_up: proba,
        pred_ret: predRet,
        edge: (2 * proba - 1) * Math.abs(predRet),
        vol_20: 0.02,
        adv_20: 1_000_000,
        entry_price: Number(p.entryPrice) || 100,
        why: why.length ? why : ['Arena pulse selection'],
        sentiment: null,
        realised_ret: null,
        side: p.side || 'long',
      };
    });

    days.push({
      date: d.date,
      equity: round2(equity),
      cash: round2(Math.max(0, equity - picks.reduce((a, p) => a + p.notional, 0))),
      pnl_today: round2(pnlToday),
      eligible_count: d.nTrades ?? picks.length,
      picks,
      settled: [],
      returnPct: retPct,
      reasoning: d.reasoning || '',
      nLong: d.nLong,
      nShort: d.nShort,
    });
    equityCurve.push({ date: d.date, equity: round2(equity) });
  }

  const g = trader.genome || {};
  const cum = Number(trader.cumulativeReturnPct) || 0;
  const config = {
    top_k: g.top_k ?? 5,
    max_position_frac: 0.2,
    max_gross_exposure: 0.9,
    kelly_scale: g.kelly ?? 0.5,
    min_proba: g.min_proba ?? 0.6,
    min_pred_ret: g.min_pred_ret ?? 0.02,
    min_vol_20: 0.01,
    cost_bps: 5,
    slippage_bps: 10,
    policy_mode: g.selection_mode || (version === 'v1' ? 'threshold_v1' : 'rank_v2'),
    exclude_pattern: '',
    short_enabled: g.short_enabled,
    short_frac: g.short_frac,
    alt_scale: g.alt_scale,
    crowd_w: g.crowd_w,
    insider_w: g.insider_w,
  };

  return {
    version: `arena-${version}-trader-${traderId}`,
    generated_at: new Date().toISOString(),
    config,
    summary: {
      starting_cash: initial,
      ending_cash: round2(equity),
      total_return_pct: cum,
      annualized_sharpe: null,
      max_drawdown_pct: estimateMaxDd(equityCurve, initial),
      trading_days: daily.length,
      trades: daily.reduce((a, d) => a + (d.nTrades || 0), 0),
      wins: null,
      losses: null,
      win_rate_pct: null,
    },
    equity_curve: equityCurve.length ? equityCurve : [{ date: days[0]?.date || '', equity: initial }],
    days: days.length ? days : [],
    price_history: {},
    _arenaMeta: {
      version,
      traderId: String(traderId),
      family: trader.family,
      genome: g,
    },
  };
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function estimateMaxDd(curve, start) {
  if (!curve.length) return 0;
  let peak = start;
  let maxDd = 0;
  for (const p of curve) {
    const e = p.equity;
    if (e > peak) peak = e;
    const dd = peak > 0 ? ((e - peak) / peak) * 100 : 0;
    if (dd < maxDd) maxDd = dd;
  }
  return Math.round(maxDd * 100) / 100;
}
