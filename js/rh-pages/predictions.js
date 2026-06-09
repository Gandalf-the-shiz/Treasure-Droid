import { api } from '../rh-api.js';

function metric(label, value, tone = '') {
  return `<div class="rh-metric">
    <div class="rh-metric__label">${label}</div>
    <div class="rh-metric__value ${tone}">${value}</div>
  </div>`;
}

function tone(n) {
  if (n == null || Number.isNaN(Number(n))) return '';
  return Number(n) > 0 ? 'rh-metric__value--green' : (Number(n) < 0 ? 'rh-metric__value--red' : '');
}

function fmtUsd(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const x = Number(n);
  const sign = x < 0 ? '-' : '';
  return `${sign}$${Math.abs(x).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function fmtPct(n) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  return `${(Number(n) * 100).toFixed(1)}%`;
}

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function exchangeBreakdown(byEx) {
  const entries = Object.entries(byEx || {});
  if (!entries.length) return '';
  const rows = entries.map(([ex, v]) => `<tr>
    <td>${esc(ex)}</td>
    <td>${v.open ?? 0}</td>
    <td>${v.resolved ?? 0}</td>
    <td class="${(v.realizedUsd || 0) >= 0 ? 'edge-pos' : 'edge-neg'}">${fmtUsd(v.realizedUsd)}</td>
    <td class="${(v.unrealizedUsd || 0) >= 0 ? 'edge-pos' : 'edge-neg'}">${fmtUsd(v.unrealizedUsd)}</td>
  </tr>`).join('');
  return `<table class="rh-table rh-table--compact"><thead><tr>
    <th>Exchange</th><th>Open</th><th>Resolved</th><th>Realized</th><th>Unrealized</th>
  </tr></thead><tbody>${rows}</tbody></table>`;
}

function betRow(p, { resolved = false } = {}) {
  const ev = p.expectedProfitUsd;
  const evTone = ev == null ? '' : (ev >= 0 ? 'edge-pos' : 'edge-neg');
  const edgePct = p.edge != null ? `${(p.edge * 100).toFixed(1)}% edge` : '';
  const headline = resolved
    ? `${esc(p.side)} · ${fmtUsd(p.pnlUsd)} realized`
    : `${esc(p.side)} · est. ${fmtUsd(ev)} profit`;
  const outcomeBlock = resolved
    ? `<dt>Outcome</dt><dd>${esc(p.outcome)} — ${fmtUsd(p.pnlUsd)} (${fmtPct(p.pnlPerDollar)} / $1)</dd>`
    : '';

  return `<details class="rh-bet-row">
    <summary>
      <div class="rh-bet-row__head">
        <span class="rh-pill">${esc(p.exchange)}</span>
        <span class="rh-bet-row__q">${esc(p.question)}</span>
        <span class="rh-bet-row__ev ${evTone}">${headline}</span>
      </div>
      <span class="rh-muted" style="font-size:11px">${edgePct} · stake ${fmtUsd(p.stakeUsd)}</span>
    </summary>
    <div class="rh-bet-row__body">
      <dl>
        <dt>Your choice</dt>
        <dd>${esc(p.choiceSummary || `${p.side} at ${fmtPct(p.price)}`)}</dd>
        <dt>Why the oracle took this side</dt>
        <dd>${esc(p.explanation || '—')}</dd>
        <dt>Math</dt>
        <dd>Model win prob ${fmtPct(p.modelWinProb ?? p.modelProb)} · Market implied ${fmtPct(p.impliedProb ?? p.price)}
          · Edge ${p.edge != null ? (p.edge * 100).toFixed(2) + '%' : '—'}
          · Expected profit ${fmtUsd(p.expectedProfitUsd)} (${p.expectedProfitPerDollar != null ? (p.expectedProfitPerDollar * 100).toFixed(1) + '¢ per $1' : '—'})</dd>
        ${outcomeBlock}
        <dt>Opened</dt>
        <dd>${esc((p.openedAt || '').slice(0, 19).replace('T', ' '))}</dd>
      </dl>
    </div>
  </details>`;
}

function positionsList(rows, { resolved = false } = {}) {
  if (!rows?.length) return '<p class="rh-muted">None inscribed.</p>';
  return rows.map((p) => betRow(p, { resolved })).join('');
}

export async function renderPredictions(main) {
  main.innerHTML = '<div class="rh-loading">Reading the prophecy markets…</div>';
  let pm;
  try {
    pm = await api.predictionMarkets();
  } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2 class="rh-card__title">Prophecy markets</h2>
      <p class="rh-muted">Could not reach the server (${e.message}).</p></section>`;
    return;
  }

  const banner = pm.available
    ? (pm.hasActivity
        ? '<span class="rh-pill rh-pill--green">Active sleeve</span>'
        : '<span class="rh-pill">Installed · idle</span>')
    : '<span class="rh-pill rh-pill--red">Not installed</span>';

  const p = pm.portfolio || {};
  const portfolioBlock = pm.hasActivity ? `
    <section class="rh-card rh-card--accent">
      <h3 class="rh-card__subtitle">Paper portfolio</h3>
      <p class="rh-muted">Separate bankroll from stocks. Snapshot: ${esc(p.generatedAt || '—')}. ${esc(p.note || '')}</p>
      <div class="rh-metrics">
        ${metric('Stake at risk', fmtUsd(p.stakeAtRiskUsd))}
        ${metric('Realized PnL', fmtUsd(p.realizedUsd), tone(p.realizedUsd))}
        ${metric('Unrealized PnL', fmtUsd(p.unrealizedUsd), tone(p.unrealizedUsd))}
        ${metric('Paper equity', fmtUsd(p.totalEquityUsd))}
        ${metric('Win rate', p.winRatePct == null ? '—' : `${p.winRatePct}%`)}
        ${metric('Return / staked $', p.returnPerStakedDollar == null ? '—' : p.returnPerStakedDollar, tone(p.returnPerStakedDollar))}
      </div>
      ${exchangeBreakdown(p.byExchange)}
    </section>` : '';

  const counts = pm.positionCounts || {};
  const openNote = counts.openTotal > counts.openShown
    ? `<p class="rh-muted">Showing ${counts.openShown} of ${counts.openTotal} open — tap each bet for the oracle’s reasoning and expected profit.</p>` : '';

  const metrics = pm.hasActivity ? `
    <div class="rh-metrics">
      ${metric('Open bets', pm.openBets)}
      ${metric('Resolved', pm.resolvedBets)}
      ${metric('Realized edge / $1', pm.realizedEdgePerDollar, tone(pm.realizedEdgePerDollar))}
      ${metric('Win rate', pm.winRatePct == null ? '—' : pm.winRatePct + '%')}
      ${metric('Brier score', pm.brierScore == null ? '—' : pm.brierScore)}
      ${metric('Alert rules', pm.nAlertRules)}
    </div>` : '';

  const triggers = (pm.recentTriggers || []).length
    ? `<h3 class="rh-card__subtitle">Recent omens (alerts)</h3><ul class="rh-list">${
        pm.recentTriggers.map((t) => `<li>${esc(t.question)} — <strong>${esc(t.side)}</strong>
          (${((t.edge || 0) * 100).toFixed(1)}% edge)</li>`).join('')}</ul>` : '';

  const positions = pm.hasActivity ? `
    <section class="rh-card">
      <h3 class="rh-card__subtitle">Open positions</h3>
      ${openNote}
      ${positionsList(pm.openPositions || [], { resolved: false })}
    </section>
    <section class="rh-card">
      <h3 class="rh-card__subtitle">Recently resolved</h3>
      ${positionsList(pm.recentResolved || [], { resolved: true })}
    </section>` : '';

  main.innerHTML = `
    <p class="rh-scroll-deco">— ✦ PROPHECY MARKETS ✦ —</p>
    <section class="rh-card">
      <div class="rh-card__head">
        <h2 class="rh-card__title">Prophecy markets ${banner}</h2>
      </div>
      <p class="rh-muted">Kalshi / Polymarket paper sleeve — math, not certainty. ${pm.note}</p>
      ${metrics}
      ${triggers}
      <p class="rh-muted" style="margin-top:14px;font-size:12px">
        Expand any bet for choice breakdown and <strong>estimated expected profit</strong> at entry.
        Live execution stays gated until forward edge is proven.
      </p>
    </section>
    ${portfolioBlock}
    ${positions}`;
}
