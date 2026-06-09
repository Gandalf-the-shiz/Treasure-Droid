import { api } from '../rh-api.js';

function heatClass(h) {
  if (h >= 75) return 'rh-pill rh-pill--green';
  if (h >= 55) return 'rh-pill';
  return 'rh-pill rh-pill--muted';
}

export async function renderPenny(main) {
  main.innerHTML = '<div class="rh-loading">Loading Penny Wolf desk…</div>';
  let data;
  try {
    data = await api.pennyOverview();
  } catch (e) {
    main.innerHTML = `<section class="rh-card"><h2 class="rh-card__title">Penny Wolf</h2>
      <p class="rh-muted">Could not load (${e.message}). Is serve.py running?</p></section>`;
    return;
  }

  const b = data.book || {};
  const retTone = (b.returnPct || 0) >= 0 ? 'edge-pos' : 'edge-neg';
  const rows = (data.heatmap || []).map((r) => `
    <tr>
      <td><strong>${r.symbol}</strong> <span class="${heatClass(r.heat)}">${r.tag || ''}</span></td>
      <td>$${Number(r.lastPx).toFixed(2)}</td>
      <td>${r.heat}</td>
      <td class="${r.ret5dPct >= 0 ? 'edge-pos' : 'edge-neg'}">${r.ret5dPct}%</td>
      <td>${(r.volSurge * 100).toFixed(0)}%</td>
      <td>${(r.predProbaUp * 100).toFixed(0)}%</td>
    </tr>`).join('');

  main.innerHTML = `
    <section class="rh-card rh-card--accent">
      <div class="rh-card__head">
        <h2 class="rh-card__title">Penny Wolf</h2>
        <span class="rh-pill">Paper only</span>
      </div>
      <p class="rh-muted">${data.tagline || ''}. ${data.disclaimer || ''}</p>
      <div class="rh-metrics">
        <div><span class="rh-metric__label">Equity</span><span class="rh-metric__value">$${(b.equity || 0).toLocaleString()}</span></div>
        <div><span class="rh-metric__label">Return</span><span class="rh-metric__value ${retTone}">${b.returnPct ?? 0}%</span></div>
        <div><span class="rh-metric__label">Open</span><span class="rh-metric__value">${b.nPositions ?? 0}</span></div>
        <div><span class="rh-metric__label">Closed</span><span class="rh-metric__value">${b.nClosed ?? 0}</span></div>
      </div>
      <p class="rh-muted">Universe: price &lt; $${data.config?.maxPriceUsd ?? 5} · min ADV ${(data.config?.minAdv20 ?? 0).toLocaleString()}</p>
      <div class="rh-row" style="margin-top:12px">
        <button type="button" class="rh-btn-primary" id="penny-tick">Run desk pulse</button>
        <button type="button" class="rh-btn-secondary" id="penny-refresh">Refresh</button>
      </div>
    </section>
    <section class="rh-card">
      <h3 class="rh-card__subtitle">Heat map — hottest sub-$5 names</h3>
      <p class="rh-muted">Desk heat blends 5-day momentum, volume surge, and Predictor tilt. Last scan: ${data.lastScan || '—'}</p>
      <table class="rh-table"><thead><tr>
        <th>Symbol</th><th>Price</th><th>Heat</th><th>5d %</th><th>Vol surge</th><th>ML up%</th>
      </tr></thead><tbody>${rows || '<tr><td colspan="6">No names — run desk pulse</td></tr>'}</tbody></table>
    </section>`;

  main.querySelector('#penny-tick')?.addEventListener('click', async () => {
    main.querySelector('#penny-tick').disabled = true;
    try {
      await api.pennyTick();
      await renderPenny(main);
    } catch (e) {
      alert(e.message);
    }
    main.querySelector('#penny-tick').disabled = false;
  });
  main.querySelector('#penny-refresh')?.addEventListener('click', () => renderPenny(main));
}
