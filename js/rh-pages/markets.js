import { api } from '../rh-api.js';

export async function renderMarkets(container, { navigate }) {
  container.innerHTML = `
    <input type="search" class="rh-search" id="rh-market-search" placeholder="Search symbol (e.g. AAPL)" autocomplete="off" />
    <p class="rh-section-title">Top ML edge (live)</p>
    <div id="rh-market-list"><div class="rh-loading">Loading…</div></div>`;

  const search = container.querySelector('#rh-market-search');
  search?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && search.value.trim()) {
      navigate('stock', search.value.trim().toUpperCase());
    }
  });

  const list = container.querySelector('#rh-market-list');
  try {
    const data = await api.livePredictions(40);
    const items = data.items || [];
    if (!items.length) {
      list.innerHTML = '<p class="rh-sub">No live predictions. Run generate_live_predictions.py.</p>';
      return;
    }
    list.innerHTML = items.map((row) => {
      const sym = row.symbol;
      const proba = Number(row.pred_proba_up);
      const edge = Number(row.edge);
      const up = proba >= 0.5;
      return `
        <div class="rh-list-item" data-symbol="${sym}" role="button" tabindex="0">
          <div style="flex:1">
            <div class="rh-symbol">${sym}</div>
            <div class="rh-sub">P(up) ${(proba * 100).toFixed(1)}% · edge ${(edge * 100).toFixed(2)}%</div>
          </div>
          <span class="rh-pill rh-pill--${up ? 'up' : 'down'}">${up ? 'Bullish' : 'Bearish'}</span>
        </div>`;
    }).join('');

    list.querySelectorAll('.rh-list-item').forEach((el) => {
      const go = () => navigate('stock', el.dataset.symbol);
      el.addEventListener('click', go);
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    });
  } catch (err) {
    list.innerHTML = `<div class="rh-error">${err.message}</div>`;
  }
}
