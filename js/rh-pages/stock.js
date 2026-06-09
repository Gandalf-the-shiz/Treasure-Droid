import { api } from '../rh-api.js';

export async function renderStock(container, symbol) {
  container.innerHTML = '<div class="rh-loading">Loading ' + symbol + '…</div>';
  try {
    const [quote, bars, news] = await Promise.all([
      api.quote(symbol),
      api.bars(symbol, 90).catch(() => ({ candles: [] })),
      api.news(symbol, 8).catch(() => ({ headlines: [] })),
    ]);

    const chg = quote.changePercent ?? 0;
    const up = chg >= 0;

    let html = `
      <button type="button" class="rh-btn-secondary" id="rh-stock-back">Back</button>
      <div class="rh-card">
        <p class="rh-card__label">${symbol}</p>
        <p class="rh-card__value ${up ? 'rh-card__value--green' : 'rh-card__value--red'}">$${Number(quote.close).toFixed(2)}</p>
        <p class="rh-sub">${up ? '+' : ''}${chg.toFixed(2)}% today · ${quote.date || ''}</p>
      </div>
      <div class="rh-chart-wrap"><canvas id="rh-stock-chart"></canvas></div>
      <p class="rh-section-title">News</p>
      <div class="rh-card" id="rh-stock-news">`;

    const headlines = news.headlines || [];
    if (!headlines.length) {
      html += '<p class="rh-sub">No headlines available.</p>';
    } else {
      html += headlines.map((h) => `
        <div class="rh-news-item">
          <a href="${h.url}" target="_blank" rel="noopener">${h.title || 'Article'}</a>
          <span class="rh-sub">${h.published || ''}</span>
        </div>`).join('');
    }
    html += '</div>';
    container.innerHTML = html;

    container.querySelector('#rh-stock-back')?.addEventListener('click', () => {
      history.back();
    });

    const candles = bars.candles || bars.bars || [];
    if (candles.length && typeof Chart !== 'undefined') {
      const ctx = document.getElementById('rh-stock-chart');
      const labels = candles.map((c) => c.date);
      const prices = candles.map((c) => c.close);
      new Chart(ctx, {
        type: 'line',
        data: {
          labels,
          datasets: [{
            data: prices,
            borderColor: '#00c805',
            backgroundColor: 'rgba(0,200,5,0.1)',
            fill: true,
            tension: 0.2,
            pointRadius: 0,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { display: false },
            y: { grid: { color: '#2a2a2a' }, ticks: { color: '#9b9b9b' } },
          },
        },
      });
    }
  } catch (err) {
    container.innerHTML = `<div class="rh-error">${err.message}</div>
      <button class="rh-btn-secondary" onclick="history.back()">Back</button>`;
  }
}
