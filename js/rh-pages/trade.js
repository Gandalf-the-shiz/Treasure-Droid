import { api } from '../rh-api.js';

function ordersHtml(manifest, label) {
  if (!manifest?.orders?.length) {
    return `<p class="rh-sub">No ${label} orders. Run generate script or wait for brain pulse.</p>`;
  }
  return manifest.orders.map((o) => `
    <div class="rh-list-item">
      <div>
        <div class="rh-symbol">${o.symbol} <span class="rh-pill">${o.side}</span></div>
        <div class="rh-sub">$${o.notional_usd || '—'} · ${o.metadata?.rationale || o.metadata?.style || ''}</div>
      </div>
    </div>`).join('');
}

export async function renderTrade(container) {
  container.innerHTML = '<div class="rh-loading">Loading trade desk…</div>';
  try {
    const [swing, day, notable] = await Promise.all([
      api.swingManifest().catch(() => null),
      api.daytradeManifest().catch(() => null),
      api.congressNotable().catch(() => ({ trades: [] })),
    ]);

    const trades = notable?.trades90d || notable?.trades || (Array.isArray(notable) ? notable : []);
    const congressList = Array.isArray(trades) ? trades.slice(0, 8) : [];

    container.innerHTML = `
      <p class="rh-section-title">Swing manifest</p>
      <div class="rh-card">${ordersHtml(swing, 'swing')}</div>
      <p class="rh-sub">Updated ${swing?.generatedAt || '—'}</p>
      <p class="rh-section-title">Daytrade manifest</p>
      <div class="rh-card">${ordersHtml(day, 'daytrade')}</div>
      <p class="rh-sub">Style: ${day?.style || 'intraday'} · refresh ${day?.refreshSeconds || 300}s</p>
      <p class="rh-section-title">Congressional notable</p>
      <div class="rh-card">
        ${congressList.length ? congressList.map((t) => `
          <div class="rh-health-row">
            <span>${t.symbol || '—'} ${t.side || ''}</span>
            <span class="rh-sub">${t.politician || t.name || ''}</span>
          </div>`).join('') : '<p class="rh-sub">No notable trades loaded.</p>'}
      </div>
      <button type="button" class="rh-btn-primary" id="rh-gen-swing">Regenerate swing</button>
      <button type="button" class="rh-btn-secondary" id="rh-gen-day">Regenerate daytrade</button>`;

    container.querySelector('#rh-gen-swing')?.addEventListener('click', async () => {
      await fetch('/api/trading/generate', { method: 'POST' });
      renderTrade(container);
    });
    container.querySelector('#rh-gen-day')?.addEventListener('click', async () => {
      await fetch('/api/daytrade/generate', { method: 'POST' });
      renderTrade(container);
    });
  } catch (err) {
    container.innerHTML = `<div class="rh-error">${err.message}</div>`;
  }
}
