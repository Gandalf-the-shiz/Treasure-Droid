/**
 * Brain logs — last 30 backtest runs + dev changelog (Cursor agent work).
 */
import { api } from '../rh-api.js';

const KIND_LABELS = {
  mad_scientist_lab: { label: 'Mad Scientist', color: '#a855f7' },
  fleet_walkforward: { label: 'Fleet walk-forward', color: '#38bdf8' },
  investor_v3: { label: 'Investor v3', color: '#22c55e' },
  harness_cycle: { label: 'Harness', color: '#9ca3af' },
};

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function fmtAt(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (_) {
    return iso;
  }
}

function kindBadge(kind) {
  const k = KIND_LABELS[kind] || { label: kind || 'Run', color: '#6b7280' };
  return `<span class="td-brain-kind" style="--kind-color:${k.color}">${esc(k.label)}</span>`;
}

function metricsLine(m = {}) {
  const parts = [];
  if (m.bestHoldSharpe != null) parts.push(`hold Sharpe <strong>${Number(m.bestHoldSharpe).toFixed(2)}</strong>`);
  if (m.sharpe != null) parts.push(`Sharpe <strong>${Number(m.sharpe).toFixed(2)}</strong>`);
  if (m.returnPct != null) parts.push(`return <strong>${Number(m.returnPct).toFixed(1)}%</strong>`);
  if (m.heldUp) parts.push(`held up <strong>${esc(m.heldUp)}</strong>`);
  if (m.nGenomes != null) parts.push(`${m.nGenomes} genomes`);
  if (m.nScored != null) parts.push(`${m.nScored} scored`);
  if (m.stepsOk != null && m.stepsTotal != null) parts.push(`<strong>${m.stepsOk}/${m.stepsTotal}</strong> steps OK`);
  return parts.length ? parts.join(' · ') : '';
}

function backtestCard(row, i) {
  const m = row.metrics || {};
  const meta = metricsLine(m);
  return `<article class="td-brain-run" data-run-idx="${i}">
    <header class="td-brain-run__head">
      ${kindBadge(row.kind)}
      <time datetime="${esc(row.at)}">${fmtAt(row.at)}</time>
    </header>
    <h3 class="td-brain-run__title">${esc(row.title)}</h3>
    <p class="td-brain-run__insight">${esc(row.insight)}</p>
    ${meta ? `<p class="td-brain-run__metrics">${meta}</p>` : ''}
    <details class="td-brain-run__more">
      <summary>Full insight</summary>
      ${row.method ? `<p><b>Method:</b> ${esc(row.method)}</p>` : ''}
      ${row.caveat ? `<p class="td-brain-run__caveat"><b>Caveat:</b> ${esc(row.caveat)}</p>` : ''}
      ${row.window ? `<p><b>Window:</b> ${esc(row.window.start)} → ${esc(row.window.end)} (${row.window.nDays ?? '—'} days)</p>` : ''}
      ${row.source ? `<p><code>${esc(row.source)}</code></p>` : ''}
    </details>
  </article>`;
}

function changelogCard(entry) {
  const tags = (entry.tags || []).map((t) => `<span class="td-brain-tag">${esc(t)}</span>`).join('');
  const areas = (entry.areas || []).slice(0, 6).map((a) => `<code>${esc(a)}</code>`).join(' ');
  return `<article class="td-brain-change">
    <header class="td-brain-change__head">
      <span class="td-brain-change__author">${esc(entry.author || 'Agent')}</span>
      <time>${fmtAt(entry.at)}</time>
    </header>
    <h3 class="td-brain-change__title">${esc(entry.title)}</h3>
    <p class="td-brain-change__summary">${esc(entry.summary)}</p>
    ${tags ? `<div class="td-brain-change__tags">${tags}</div>` : ''}
    ${areas ? `<div class="td-brain-change__areas">${areas}</div>` : ''}
  </article>`;
}

export function brainLogsHtml(data) {
  const harness = data.harness || {};
  const runs = data.backtests || [];
  const changes = data.devChangelog || [];

  return `
    <div class="td-brain-page">
      <div class="td-brain-hero">
        <h2>App brain insights</h2>
        <p>Automatic log of the last <strong>30</strong> Treasure Droid backtest runs, plus a changelog of Cursor agent work on the app.</p>
        <div class="td-brain-live">
          <div class="td-brain-stat"><span>Harness</span><strong>${esc(harness.phase || 'idle')}</strong><small>${esc(harness.mode || '')}</small></div>
          <div class="td-brain-stat"><span>Backtests logged</span><strong>${runs.length}</strong><small>max 30 retained</small></div>
          <div class="td-brain-stat"><span>Dev changes</span><strong>${changes.length}</strong><small>agent sessions</small></div>
        </div>
      </div>

      <nav class="td-brain-tabs" aria-label="Brain log sections">
        <button type="button" class="td-brain-tab td-brain-tab--active" data-brain-tab="backtests">Backtest log</button>
        <button type="button" class="td-brain-tab" data-brain-tab="changelog">Dev changelog</button>
      </nav>

      <section data-brain-panel="backtests" class="td-brain-panel">
        <p class="rh-muted" style="font-size:12px;margin-bottom:12px">
          Each harness cycle, Mad Scientist lab, fleet walk-forward, and Investor v3 train appends here with a plain-English insight.
        </p>
        ${runs.length
    ? `<div class="td-brain-run-list">${runs.map((r, i) => backtestCard(r, i)).join('')}</div>`
    : '<p class="rh-muted">No backtests logged yet — they appear after the next harness or lab run.</p>'}
      </section>

      <section data-brain-panel="changelog" class="td-brain-panel" hidden>
        <p class="rh-muted" style="font-size:12px;margin-bottom:12px">
          When you ask Cursor to work on Treasure Droid, the agent records what changed and why.
        </p>
        ${changes.length
    ? `<div class="td-brain-change-list">${changes.map(changelogCard).join('')}</div>`
    : '<p class="rh-muted">No dev changelog entries yet.</p>'}
      </section>
    </div>`;
}

export function bindBrainLogsTabs(container) {
  const root = container.querySelector('.td-brain-page');
  if (!root) return;
  root.querySelectorAll('[data-brain-tab]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.brainTab;
      root.querySelectorAll('[data-brain-tab]').forEach((b) => {
        b.classList.toggle('td-brain-tab--active', b.dataset.brainTab === id);
      });
      root.querySelectorAll('[data-brain-panel]').forEach((p) => {
        p.hidden = p.dataset.brainPanel !== id;
      });
    });
  });
}

export async function fetchBrainInsights() {
  return api.brainInsights();
}
