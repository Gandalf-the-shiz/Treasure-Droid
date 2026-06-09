import { api } from '../rh-api.js';
import {
  fmt, tabStrip, bindTabs, drillKpi, bindDrills, accordionSection, dockTile, chartCard,
} from '../rh-components.js';
import { renderLineChart, renderBarChart, destroyChart, PROFIT, LOSS, GOLD } from '../rh-charts.js';

let _charts = [];

function killCharts() {
  _charts.forEach((c) => destroyChart(c));
  _charts = [];
}

function bigTile({ label, value, sub, tone = 'neutral' }) {
  return `<div class="rh-bigtile rh-bigtile--${tone}">
    <p class="rh-bigtile__label">${label}</p>
    <p class="rh-bigtile__value rh-bigtile__value--${tone}">${value}</p>
    <p class="rh-bigtile__sub">${sub || ''}</p>
  </div>`;
}

function topTraderCard(t, i) {
  const tone = (t.returnPct || 0) >= 0 ? 'ok' : 'neg';
  const crown = i === 0 ? '<span class="td-top-trader__crown" title="Top trader">👑</span>' : '';
  const perf = t.performance || {};
  const retLabel = perf.label || (t.source === 'fleet' ? 'Forward paper' : 'Arena sim');
  return `<a class="td-top-trader td-top-trader--${tone}" href="${t.href || '#'}">
    <header class="td-top-trader__head">
      <div>
        <span class="td-top-trader__rank">#${t.rank ?? i + 1}</span>
        <h3 class="td-top-trader__name">${t.name || t.id}${crown}</h3>
        <span class="td-top-trader__badge">${t.badge || t.source}</span>
      </div>
      <div class="td-top-trader__ret">
        <span class="td-top-trader__ret-val">${fmt(t.returnPct, 'pctSigned')}</span>
        <span class="td-top-trader__ret-lbl">${retLabel}</span>
      </div>
    </header>
    <p class="td-top-trader__bio">${t.bio || '—'}</p>
    <dl class="td-top-trader__meta">
      <div><dt>Book</dt><dd>${t.portfolio || '—'}</dd></div>
      <div><dt>Equity</dt><dd>${t.equityUsd != null ? fmt(t.equityUsd, 'usd') : '—'}</dd></div>
      ${t.nDays != null ? `<div><dt>Days live</dt><dd>${t.nDays}</dd></div>` : ''}
      ${t.dayPnl != null ? `<div><dt>Today</dt><dd class="${t.dayPnl >= 0 ? 'edge-pos' : 'edge-neg'}">${t.dayPnl >= 0 ? '+' : ''}${fmt(t.dayPnl, 'usd2')}</dd></div>` : ''}
    </dl>
    <span class="td-top-trader__cta">Open trader book →</span>
  </a>`;
}

function topTradersSection(traders) {
  if (!traders?.length) {
    return `<section class="td-top-traders td-top-traders--empty">
      <p class="td-section-label">Top traders</p>
      <p class="rh-muted" style="font-size:13px">Arena pulse + fleet forward will populate the leaderboard.</p>
    </section>`;
  }
  return `<section class="td-top-traders" aria-label="Top traders">
    <p class="td-section-label">Top traders · fleet + arena</p>
    <p class="td-top-traders__intro">Best performers across forward-paper spawns and ML arena genomes right now.</p>
    <div class="td-top-traders__grid">${traders.map((t, i) => topTraderCard(t, i)).join('')}</div>
  </section>`;
}

function modelRow(m) {
  const metrics = (m.metrics || []).slice(0, 3).map((mt) =>
    `<span class="td-model-row__m">${mt.label} <b>${fmt(mt.value, mt.fmt)}</b></span>`).join('');
  return `<div class="td-model-row">
    <div class="td-model-row__left">
      <span class="td-model-row__name">${m.name}</span>
      <span class="rh-badge rh-badge--${m.status}">${m.status}</span>
    </div>
    <div class="td-model-row__metrics">${metrics}</div>
  </div>`;
}

export async function renderHome(container) {
  killCharts();
  container.innerHTML = '<div class="rh-loading">The droid is counting your coins…</div>';
  let cc;
  try {
    cc = await api.commandCenter();
  } catch (err) {
    container.innerHTML = `<div class="rh-error">Droid offline. Boot <code>python scripts/serve.py</code><br>${err.message}</div>`;
    return;
  }

  let alpaca = null;
  let topTraders = { traders: [] };
  try { alpaca = await api.alpacaAccount(); } catch (_) { alpaca = null; }
  try { topTraders = await api.bridgeTopTraders(3); } catch (_) { topTraders = { traders: [] }; }

  const score = cc.healthScore ?? 0;
  const pipe = cc.pipeline || {};
  const okCount = (cc.healthChecks || []).filter((c) => c.ok).length;
  const total = (cc.healthChecks || []).length;
  const ft = cc.forwardTruth || {};
  const ftMetrics = ft.metrics || [];
  const gatesGreen = ftMetrics.filter((m) => m.ok).length;
  const book = cc.alphaBook || {};
  const sleeveIc = cc.sleeveIc || {};
  const madLab = cc.madScientistLab || {};
  const paperState = cc.alpacaPaper || {};
  const trends = cc.trends || {};
  const liveOk = ft.liveTradingPermitted;
  const verdictTone = liveOk ? 'ok' : 'warn';

  const equity = alpaca?.ok ? alpaca.equity : null;
  const dayChange = alpaca?.ok ? alpaca.dayChangePct : null;
  const upl = alpaca?.ok ? alpaca.unrealizedPl : null;
  const paperTone = upl == null ? 'neutral' : (upl > 0 ? 'ok' : (upl < 0 ? 'neg' : 'neutral'));
  const alphaSpread = ftMetrics.find((m) => m.id === 'alpha_spread');
  const alphaIcir = ftMetrics.find((m) => m.id === 'alpha_icir');

  const tabs = [
    { id: 'overview', label: 'Overview', icon: '◎' },
    { id: 'performance', label: 'Scoreboard', icon: '▣' },
    { id: 'alpha', label: 'Alpha', icon: '◆' },
    { id: 'lab', label: 'Lab', icon: '🧪' },
    { id: 'systems', label: 'Systems', icon: '⚙' },
  ];

  let html = `
    <header class="td-hero-compact">
      <div class="td-hero-compact__brand">
        <img class="td-hero-compact__icon" src="assets/treasure-droid-icon.png" alt="" width="48" height="48" />
        <div>
          <h1 class="td-hero-compact__name">TREASURE DROID</h1>
          <p class="td-hero-compact__motto">Greedy. Forward. Paper until the edge screams yes.</p>
        </div>
      </div>
      <span class="td-hero-compact__pill td-hero-compact__pill--${verdictTone}">
        ${liveOk ? 'CAPITAL READY' : 'MAD SCIENTIST MODE'}
      </span>
    </header>

    <section class="rh-glass-hero rh-glass-hero--${verdictTone} td-hero-strip">
      <div class="rh-glass-hero__verdict">
        <h2 class="rh-glass-hero__headline">${gatesGreen}/${ftMetrics.length} gates green</h2>
        <p class="rh-glass-hero__sub">I hoard forward proof, not backtest fairy tales. Tap any section below to drill in.</p>
      </div>
      <div class="rh-glass-hero__tiles">
        ${bigTile({
          label: 'Paper equity',
          value: equity != null ? fmt(equity, 'usd') : '—',
          sub: equity != null ? `${dayChange >= 0 ? '+' : ''}${dayChange?.toFixed(2)}% today` : 'Connect Alpaca',
          tone: paperTone,
        })}
        ${bigTile({
          label: 'Open P&L',
          value: upl != null ? `${upl >= 0 ? '+' : ''}${fmt(upl, 'usd2')}` : '—',
          sub: 'Unrealized · fake money, real prices',
          tone: paperTone,
        })}
        ${bigTile({
          label: 'Alpha edge',
          value: alphaSpread ? alphaSpread.display : '—',
          sub: `ICIR ${alphaIcir ? alphaIcir.display : '—'}`,
          tone: alphaSpread?.ok ? 'ok' : 'warn',
        })}
      </div>
    </section>

    ${tabStrip('td-bridge-tabs', tabs, 'overview')}

    <div class="td-panels" id="td-bridge-panels">
      <section class="td-panel" data-panel="overview">
        ${topTradersSection(topTraders.traders)}
        <div class="td-chart-grid">
          ${chartCard('Investor equity curve', 'Backtest book · click Fleet for per-spawn forward curves', 'chart-investor-eq', 200)}
          ${chartCard('Predictor hit rate', 'v2 accuracy trend · research window', 'chart-accuracy', 180)}
        </div>
        ${!liveOk && (ft.reasons || []).length ? `
          <div class="td-callout td-callout--warn">
            <strong>Still on paper.</strong> ${ft.reasons[0]}
            ${ft.reasons.length > 1 ? ` <button type="button" class="td-link-btn" id="td-show-gates">+${ft.reasons.length - 1} more</button>` : ''}
            <ul class="td-callout__list" id="td-gate-list" hidden>${ft.reasons.slice(1).map((r) => `<li>${r}</li>`).join('')}</ul>
          </div>` : ''}
        <p class="td-section-label">Spawn charts · tap to open</p>
        <div class="td-spawn-links">
          <a class="td-spawn-link" href="#/fleet"><span class="td-spawn-link__icon">🏴‍☠️</span><span>Fleet agents</span><span class="td-spawn-link__hint">Per-trader equity + picks</span></a>
          <a class="td-spawn-link" href="#/arena"><span class="td-spawn-link__icon">⚔</span><span>Arena genomes</span><span class="td-spawn-link__hint">200 ML traders compared</span></a>
          <a class="td-spawn-link" href="#/investor"><span class="td-spawn-link__icon">◇</span><span>Investor book</span><span class="td-spawn-link__hint">Day-by-day playback</span></a>
        </div>
      </section>

      <section class="td-panel" data-panel="performance" hidden>
        <p class="td-panel-intro">Forward metrics first. Tap a row for the full explanation.</p>
        <div class="td-drill-grid">
          ${ftMetrics.map((m, i) => drillKpi({
            id: `ft-${i}`,
            label: m.label,
            value: m.display ?? '—',
            tone: m.ok ? 'ok' : 'warn',
            tag: m.kind === 'forward' ? 'FWD' : 'RES',
            detail: m.explain || '',
          })).join('')}
        </div>
        ${accordionSection({
          id: 'acc-book',
          title: 'Market-neutral book',
          summary: `${paperState.nLong ?? book.nLong ?? 0}L / ${paperState.nShort ?? book.nShort ?? 0}S · net ${fmt(paperState.netExposure ?? book.netExposure, typeof (paperState.netExposure ?? book.netExposure) === 'number' && Math.abs(paperState.netExposure ?? book.netExposure) > 100 ? 'usd' : 'num4')}`,
          bodyHtml: `<div class="td-drill-grid">
            ${drillKpi({ id: 'bk-1', label: 'Sleeves blended', value: (book.sleeves || []).length || '—', tone: 'ok', detail: (book.sleeves || []).join(', ') || '—' })}
            ${drillKpi({ id: 'bk-2', label: 'Universe scanned', value: book.universe ?? '—', tone: 'neutral', detail: 'Liquid names ranked each cycle.' })}
            ${drillKpi({ id: 'bk-3', label: 'Buying power', value: alpaca?.ok ? fmt(alpaca.buyingPower, 'usd') : '—', tone: 'neutral', detail: 'Paper margin available.' })}
          </div>`,
        })}
      </section>

      <section class="td-panel" data-panel="alpha" hidden>
        ${(sleeveIc.sleeves || []).length ? `
          ${chartCard('Sleeve forward IC', `Weights: ${sleeveIc.weightMode || 'static'}`, 'chart-sleeves', 220)}
          <div class="rh-sleeve-table-wrap">
            <table class="rh-sleeve-table">
              <thead><tr><th>Sleeve</th><th>Fwd IC</th><th>ICIR</th><th>Research</th><th>Wt</th></tr></thead>
              <tbody>
                ${(sleeveIc.sleeves || []).map((s) => {
                  const tone = s.decayed ? 'neg' : (s.forwardIc > 0 ? 'ok' : 'warn');
                  return `<tr class="rh-sleeve-row rh-sleeve-row--${tone}">
                    <td>${s.label || s.id}${s.decayed ? ' <span class="rh-sleeve-decay">DECAY</span>' : ''}</td>
                    <td>${s.forwardIc != null ? fmt(s.forwardIc, 'num4') : '—'}</td>
                    <td>${s.forwardIcir != null ? fmt(s.forwardIcir, 'num3') : '—'}</td>
                    <td>${s.researchIc != null ? fmt(s.researchIc, 'num4') : '—'}</td>
                    <td>${s.effectiveWeight != null ? fmt(s.effectiveWeight, 'num3') : '—'}</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>` : '<p class="rh-muted">No sleeve IC yet — run daily close.</p>'}
      </section>

      <section class="td-panel" data-panel="lab" hidden>
        ${madLab.ok ? `
          <div class="td-drill-grid">
            ${drillKpi({ id: 'lab-1', label: 'Walk-forward', value: madLab.window?.start ? `${madLab.window.start} → ${madLab.window.end}` : '—', tone: 'ok', detail: `${madLab.window?.nDays || '—'} days · 8yr train, 2yr walk` })}
            ${drillKpi({ id: 'lab-2', label: 'Best holdout Sharpe', value: madLab.bestHoldoutSharpe != null ? fmt(madLab.bestHoldoutSharpe, 'num3') : '—', tone: (madLab.bestHoldoutSharpe || 0) > 0.5 ? 'ok' : 'warn', detail: 'Upper bound until forward paper proves it.' })}
            ${drillKpi({ id: 'lab-3', label: 'Genomes / survivors', value: `${madLab.nGenomes || '—'} / ${madLab.nSurvivors || 0}`, tone: 'neutral', detail: 'Promoted to shadow fleet (MS-*).' })}
            ${drillKpi({ id: 'lab-4', label: 'Panel rows', value: madLab.panel?.rows != null ? fmt(madLab.panel.rows, 'int') : '—', tone: 'neutral', detail: 'Historical panel matching live machine outputs.' })}
          </div>
          ${madLab.verdict ? `<p class="td-lab-verdict">${madLab.verdict}</p>` : ''}
          <a href="#/megamind" class="td-link-card">Captain's lab report →</a>` : '<p class="rh-muted">Mad Scientist lab idle — autonomous loop will kick a cycle.</p>'}
      </section>

      <section class="td-panel" data-panel="systems" hidden>
        <div class="td-systems-row">
          <div class="td-health-ring">
            <span class="td-health-ring__score" style="color:${score >= 75 ? GOLD : score >= 50 ? '#ffb020' : LOSS}">${score}</span>
            <span class="td-health-ring__cap">health</span>
          </div>
          <div class="td-systems-chips">
            <span class="rh-chip rh-chip--ok">${okCount}/${total} channels</span>
            <span class="rh-chip">${pipe.mode || 'brain'}</span>
            <span class="rh-chip">${(pipe.npu || 'CPU').replace('ExecutionProvider', '')}</span>
          </div>
        </div>
        ${accordionSection({
          id: 'acc-channels',
          title: 'Data channels',
          summary: `${okCount} live · ${total - okCount} need attention`,
          bodyHtml: `<div class="rh-channels">${(cc.healthChecks || []).map((c) => `
            <div class="rh-health-row">
              <div class="rh-health-row__left"><span class="rh-dot ${c.ok ? 'rh-dot--ok' : 'rh-dot--bad'}"></span><span>${c.label}</span></div>
              <span class="rh-sub">${c.detail || ''}</span>
            </div>`).join('')}</div>`,
        })}
        ${accordionSection({
          id: 'acc-engines',
          title: 'ML engines',
          summary: `${(cc.models || []).length} models`,
          bodyHtml: `<div class="td-model-list">${(cc.models || []).map(modelRow).join('')}</div>`,
        })}
      </section>
    </div>`;

  const modules = cc.appModules || [];
  if (modules.length) {
    html += `<nav class="td-dock" aria-label="Cargo holds">
      <p class="td-dock__label">Cargo holds</p>
      <div class="td-dock__scroll">${modules.map(dockTile).join('')}</div>
    </nav>`;
  }

  html += `<div class="rh-home-foot">
    <button type="button" class="rh-btn-secondary" id="rh-goto-arch">Schematics</button>
    <button type="button" class="rh-btn-secondary" id="rh-goto-brain">Brain logs</button>
    <button type="button" class="rh-btn-secondary" id="rh-goto-captain">Captain</button>
  </div>`;

  container.innerHTML = html;

  const tabRoot = container.querySelector('#td-bridge-tabs');
  bindTabs(tabRoot);
  bindDrills(container);

  container.querySelectorAll('.td-dock__tile').forEach((btn) => {
    btn.addEventListener('click', () => { location.hash = `#/${btn.dataset.route}`; });
  });
  container.querySelector('#rh-goto-arch')?.addEventListener('click', () => { location.hash = '#/architecture'; });
  container.querySelector('#rh-goto-brain')?.addEventListener('click', () => { location.hash = '#/architecture/brain'; });
  container.querySelector('#rh-goto-captain')?.addEventListener('click', () => { location.hash = '#/megamind'; });
  container.querySelector('#td-show-gates')?.addEventListener('click', () => {
    const list = container.querySelector('#td-gate-list');
    if (list) list.hidden = !list.hidden;
  });

  await paintCharts(container, trends, sleeveIc);
}

async function paintCharts(container, trends, sleeveIc) {
  if (!window.Chart) {
    await new Promise((r) => {
      const t = setInterval(() => { if (window.Chart) { clearInterval(t); r(); } }, 50);
      setTimeout(r, 3000);
    });
  }

  const eq = trends.investorEquity || [];
  if (eq.length) {
    const c = renderLineChart(container.querySelector('#chart-investor-eq'), {
      labels: eq.map((p) => p.date),
      values: eq.map((p) => p.equity),
      label: 'Equity',
      color: PROFIT,
    });
    if (c) _charts.push(c);
  }

  const acc = trends.v2Accuracy || [];
  if (acc.length) {
    const c = renderLineChart(container.querySelector('#chart-accuracy'), {
      labels: acc.map((p) => p.date),
      values: acc.map((p) => (p.hitRate != null ? p.hitRate * (p.hitRate <= 1 ? 100 : 1) : null)),
      label: 'Hit %',
      color: GOLD,
      fill: false,
    });
    if (c) _charts.push(c);
  }

  const sleeves = sleeveIc.sleeves || [];
  if (sleeves.length) {
    const c = renderBarChart(container.querySelector('#chart-sleeves'), {
      labels: sleeves.map((s) => s.label || s.id),
      values: sleeves.map((s) => s.forwardIc ?? 0),
      colors: sleeves.map((s) => (s.forwardIc > 0 ? PROFIT : LOSS)),
    });
    if (c) _charts.push(c);
  }
}
