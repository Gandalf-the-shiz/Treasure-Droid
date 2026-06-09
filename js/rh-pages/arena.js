import { api } from '../rh-api.js';
import { arenaTraderToBookData } from '../ui/book-adapter.js';
import { renderInvestorBook } from '../ui/investor.js';

let compareChart = null;

function pctClass(v) {
  return (v || 0) >= 0 ? 'edge-pos' : 'edge-neg';
}

function navigate(hash) {
  location.hash = hash;
}

function destroyChart(ch) {
  if (ch) ch.destroy();
  return null;
}

function fmtRet(v) {
  if (v == null || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const pct = Math.abs(n) <= 1.5 ? n * 100 : n;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function fmtUsd(v) {
  if (v == null) return '—';
  return `$${Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function metricBox(label, value, tone = '') {
  return `<div class="rh-metric">
    <p class="rh-metric__label">${label}</p>
    <p class="rh-metric__value ${tone}">${value}</p>
  </div>`;
}

async function renderOverview(main, stale = () => false) {
  main.innerHTML = '<div class="rh-loading">Loading Investor Arena…</div>';
  let exp;
  let cmp;
  let ultimate;
  try {
    [exp, cmp] = await Promise.all([api.arenaExperiment(), api.arenaCompare()]);
    ultimate = await api.megamind().catch(() => api.ultimateModel().catch(() => null));
  } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2>Investor Arena</h2>
      <p class="rh-muted">Could not load (${e.message}). Run migrate + pulse on serve host.</p>
      <button type="button" class="rh-btn-primary" id="arena-pulse">Run arena pulse</button></section>`;
    main.querySelector('#arena-pulse')?.addEventListener('click', async () => {
      await api.arenaPulse();
      renderOverview(main);
    });
    return;
  }
  if (stale()) return;

  const versionList = exp.versionList || cmp.versions || ['v1', 'v2'];
  const summaries = cmp.versionSummaries || { v1: cmp.v1Summary, v2: cmp.v2Summary };
  const meta = exp.versions || {};
  const leader = cmp.leadingVersion || null;
  const palette = ['#00c805', '#7c5cff', '#ff9500', '#ff5000', '#5ac8fa'];
  const cards = versionList.map((v, i) => {
    const s = summaries[v] || {};
    const m = meta[v] || {};
    const frozen = m.frozen ? ' · frozen baseline' : '';
    const mode = m.selectionMode || (v === 'v1' ? 'threshold' : 'rank-unified');
    return `<div class="arena-card ${leader === v ? 'arena-card--winner' : ''}" data-go="#/arena/${v}">
        <div class="arena-card__label">Investor Arena ${v}${m.frozen ? ' 🔒' : ''}</div>
        <div class="arena-card__value ${pctClass(s.meanCumulativePct)}">${s.meanCumulativePct ?? '—'}%</div>
        <p class="rh-muted">Mean cumulative · ${mode}${frozen} · ${s.nTraders ?? m.nTraders ?? 100} traders</p>
        <p class="rh-muted">Leader <span class="rh-arch-leader-id">#${s.topTraderId ?? '—'}</span>
          ${s.topTraderId != null ? '<span class="rh-arch-leader-badge">Leader</span>' : ''}
          at <strong>${s.bestCumulativePct ?? '—'}%</strong></p>
        ${m.label && !m.frozen ? `<p class="rh-muted" style="font-size:11px">${m.label}</p>` : ''}
      </div>`;
  }).join('');

  const compareNote = leader
    ? `${leader} leading on mean cumulative return. v1/v2 frozen; new arms are Megamind spawns only.`
    : (cmp.v2BeatingV1 === true ? 'v2 leading.' : cmp.v2BeatingV1 === false ? 'v1 ahead.' : 'Insufficient history — run more pulses.');

  main.innerHTML = `
    <section class="rh-card rh-card--accent">
      <h2 class="rh-card__title">Investor Arena</h2>
      <p class="rh-muted">${exp.label || 'Multi-arm experiment'} · sim returns (not live PnL)</p>
      <div class="arena-breadcrumb">
        <span>Arms: ${versionList.join(', ')} · since ${(exp.startedAt || '').slice(0, 10)}</span>
        <button type="button" class="rh-btn-secondary" id="arena-pulse" title="Manual re-run; daily 5:00 PM job usually handles this">Pulse now</button>
        <button type="button" class="rh-btn-secondary" id="arena-refresh">Refresh</button>
      </div>
      <p class="rh-muted" style="margin-top:8px;font-size:12px">Post-close update runs automatically at 5:00 PM Eastern (Mon–Fri). v1/v2 are frozen; Megamind may add v3+ only.</p>
    </section>
    <section class="arena-hero">${cards}</section>
    <section class="rh-card">
      <h3 class="rh-card__subtitle">Cohort equity index (100 = start)</h3>
      <div class="arena-chart-wrap"><canvas id="arena-compare-chart"></canvas></div>
      <p class="rh-muted">${compareNote}</p>
    </section>
    ${ultimate ? `
    <section class="rh-card arena-ultimate">
      <h3 class="rh-card__subtitle">Megamind · ${ultimate.agent || ultimate.status || 'scheming'}</h3>
      <p class="rh-muted">${(ultimate.generatedAt || '').slice(0, 19)} UTC · ${ultimate.nPending ?? 0} pending approvals</p>
      <p>${(ultimate.narrative || '').slice(0, 600)}${(ultimate.narrative || '').length > 600 ? '…' : ''}</p>
      <a href="#/megamind" class="rh-btn-primary" style="display:inline-block;margin-top:8px;text-decoration:none">Review &amp; approve recommendations →</a>
    </section>` : `
    <section class="rh-card"><p class="rh-muted">Megamind not run yet — included in daily 5:00 PM update</p></section>`}`;

  main.querySelectorAll('[data-go]').forEach((el) => {
    el.addEventListener('click', () => navigate(el.dataset.go));
  });
  main.querySelector('#arena-pulse')?.addEventListener('click', async () => {
    main.querySelector('#arena-pulse').disabled = true;
    try {
      await api.arenaPulse();
      await renderOverview(main);
    } catch (err) {
      alert(err.message);
    }
    main.querySelector('#arena-pulse').disabled = false;
  });
  main.querySelector('#arena-refresh')?.addEventListener('click', () => renderOverview(main));

  const ctx = main.querySelector('#arena-compare-chart');
  if (ctx && window.Chart) {
    compareChart = destroyChart(compareChart);
    const indexes = cmp.versionEquityIndexes || {};
    const datasets = versionList.map((v, i) => ({
      label: `${v} cohort`,
      data: indexes[v] || cmp[`${v}EquityIndex`] || [],
      borderColor: palette[i % palette.length],
      backgroundColor: `${palette[i % palette.length]}22`,
      tension: 0.25,
      fill: i === 0,
    }));
    compareChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: cmp.dates || [],
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { labels: { color: '#ccc' } } },
        scales: {
          x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.06)' } },
          y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.06)' } },
        },
      },
    });
  }
}

async function renderGroup(main, version, stale = () => false) {
  main.innerHTML = '<div class="rh-loading">Loading leaderboard…</div>';
  let traders;
  try {
    const res = await api.arenaTraders(version);
    traders = res.traders || [];
  } catch (e) {
    if (stale()) return;
    main.innerHTML = `<p class="rh-muted">Failed: ${e.message}</p>`;
    return;
  }
  if (stale()) return;

  const label = `Investor Arena ${version}`;
  const rows = traders.map((t) => {
    const last = (t.daily || [])[t.daily.length - 1] || {};
    const rank = Number(t.rank) || 99;
    const rowCls = rank === 1 ? 'arena-table-row--leader'
      : rank <= 3 ? 'arena-table-row--podium' : '';
    const leaderBadge = rank === 1 ? '<span class="rh-arch-leader-badge">Leader</span>' : '';
    return `<tr data-id="${t.traderId}" class="${rowCls}">
      <td class="arena-rank">#${t.rank}</td>
      <td><strong>${t.traderId}</strong>${leaderBadge} <span class="rh-pill">${t.family || ''}</span></td>
      <td class="${pctClass(t.cumulativeReturnPct)}">${t.cumulativeReturnPct}%</td>
      <td>$${(t.equityUsd || 0).toLocaleString()}</td>
      <td>${t.nDays || 0}</td>
      <td>${last.nTrades ?? 0}</td>
      <td class="${pctClass(last.returnPct)}">${last.returnPct ?? 0}%</td>
    </tr>`;
  }).join('');

  main.innerHTML = `
    <div class="arena-breadcrumb">
      <a href="#/arena">← Arena</a>
      <span>/</span>
      <strong>${label}</strong>
    </div>
    <section class="rh-card">
      <h2 class="rh-card__title">${label}</h2>
      <p class="rh-muted">Stack ranked by cumulative return since experiment start (simulated).</p>
      <table class="rh-table arena-table"><thead><tr>
        <th>#</th><th>Trader</th><th>Cum %</th><th>Equity</th><th>Days</th><th>Last trades</th><th>Last day %</th>
      </tr></thead><tbody>${rows || '<tr><td colspan="7">No ledger data</td></tr>'}</tbody></table>
    </section>`;

  main.querySelectorAll('.arena-table tr[data-id]').forEach((tr) => {
    tr.addEventListener('click', () => navigate(`#/arena/${version}/${tr.dataset.id}`));
  });
}

async function renderTrader(main, version, traderId, stale) {
  main.innerHTML = '<div class="rh-loading">Loading trader…</div>';
  let t;
  let isArenaLeader = false;
  try {
    const [detail, board] = await Promise.all([
      api.arenaTrader(version, traderId),
      api.arenaTraders(version).catch(() => ({ traders: [] })),
    ]);
    t = detail;
    const row = (board.traders || []).find((x) => String(x.traderId) === String(traderId));
    isArenaLeader = row?.rank === 1;
  } catch (e) {
    if (stale?.()) return;
    main.innerHTML = `<section class="rh-card"><p class="rh-muted">Trader #${traderId} — ${e.message}</p>
      <a href="#/arena/${version}">← Back to ${version}</a></section>`;
    return;
  }
  if (stale?.()) return;

  const book = arenaTraderToBookData(t, { version, traderId });
  main.innerHTML = '<div class="rh-inv-mount arena-book-mount"></div>';
  const mount = main.querySelector('.arena-book-mount');
  const leaderNote = isArenaLeader ? ' · arena leader' : '';
  await renderInvestorBook(mount, book, {
    breadcrumbHtml: `
      <a href="#/arena">Arena</a><span> / </span>
      <a href="#/arena/${version}">${version.toUpperCase()}</a><span> / </span>
      <strong>Trader ${traderId}</strong>`,
    title: `⚔ Arena ${version.toUpperCase()} · Trader ${traderId}`,
    subtitle: `${t.family || 'Genome'}${leaderNote} — same day-by-day book view as Investor v3 (simulated pred_ret, not live fills).`,
    showRetrain: false,
    showCommandCenter: false,
  });
  if (stale?.()) return;
}

export async function renderArena(main, route = {}, stale = () => false) {
  const version = route.version;
  const traderId = route.traderId;
  if (version && traderId != null) await renderTrader(main, version, traderId, stale);
  else if (version) await renderGroup(main, version, stale);
  else await renderOverview(main, stale);
}
