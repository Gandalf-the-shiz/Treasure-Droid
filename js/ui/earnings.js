import { getEarningsCalendar } from '../api/manager.js';
import { getWatchlist } from './watchlist.js';
import { escapeHtml as _esc } from '../utils/helpers.js';

// Demo earnings defined as day-offsets from today so they are always in the future.
const DEMO_EARNINGS = [
  { symbol: 'JPM',   daysFromNow: 3,  hour: 'BMO', epsEstimate: 4.12 },
  { symbol: 'TSLA',  daysFromNow: 4,  hour: 'AMC', epsEstimate: 0.61 },
  { symbol: 'JNJ',   daysFromNow: 5,  hour: 'BMO', epsEstimate: 2.57 },
  { symbol: 'GOOGL', daysFromNow: 6,  hour: 'AMC', epsEstimate: 1.93 },
  { symbol: 'AAPL',  daysFromNow: 7,  hour: 'AMC', epsEstimate: 1.62 },
  { symbol: 'MSFT',  daysFromNow: 9,  hour: 'AMC', epsEstimate: 2.87 },
  { symbol: 'AMZN',  daysFromNow: 11, hour: 'AMC', epsEstimate: 1.14 },
  { symbol: 'META',  daysFromNow: 14, hour: 'AMC', epsEstimate: 5.28 },
  { symbol: 'V',     daysFromNow: 18, hour: 'AMC', epsEstimate: 2.65 },
  { symbol: 'NVDA',  daysFromNow: 20, hour: 'AMC', epsEstimate: 0.94 },
];

/** Build demo rows with real calendar dates computed from today. */
function _buildDemoRows() {
  const today = new Date();
  return DEMO_EARNINGS.map(e => {
    const d = new Date(today);
    d.setDate(d.getDate() + e.daysFromNow);
    return { symbol: e.symbol, date: d.toISOString().slice(0, 10), hour: e.hour, epsEstimate: e.epsEstimate };
  });
}

export async function renderEarningsView(container, appState) {
  container.innerHTML = '';

  const title = document.createElement('h2');
  title.className = 'backtest-title';
  title.textContent = '📅 Upcoming Earnings';
  container.appendChild(title);

  const watchlist = getWatchlist();
  let rows = [];

  if (appState.mode === 'demo') {
    // Demo mode: always show sample earnings so the view is never empty.
    // If the watchlist has matching symbols, highlight only those; otherwise show all.
    const all = _buildDemoRows();
    const matched = watchlist.length ? all.filter(e => watchlist.includes(e.symbol)) : [];
    rows = matched.length ? matched : all;

    const note = document.createElement('p');
    note.className = 'heatmap-demo-note';
    note.textContent = matched.length
      ? 'Showing demo earnings for your watchlisted symbols.'
      : 'Demo mode — showing sample upcoming earnings. Add symbols to your watchlist to filter.';
    container.appendChild(note);
  } else {
    // Live mode: require a watchlist.
    if (!watchlist.length) {
      container.innerHTML += '<p class="accuracy-empty-note">Add symbols to your watchlist to see upcoming earnings.</p>';
      return;
    }

    // Detect missing Finnhub key early and surface a helpful CTA.
    const hasFinnhubKey = !!localStorage.getItem('finnhub_key');
    if (!hasFinnhubKey) {
      const msg = document.createElement('p');
      msg.className = 'accuracy-empty-note';
      msg.innerHTML = `A <strong>Finnhub API key</strong> is required to load live earnings data.
        Configure it in <a href="#" id="earnings-settings-link">⚙ Settings</a>.`;
      container.appendChild(msg);
      container.querySelector('#earnings-settings-link')?.addEventListener('click', e => {
        e.preventDefault();
        document.getElementById('nav-settings')?.click();
      });
      return;
    }

    const from = new Date().toISOString().slice(0, 10);
    const toD = new Date();
    toD.setDate(toD.getDate() + 30);
    const to = toD.toISOString().slice(0, 10);
    const all = await getEarningsCalendar(from, to);
    rows = (all || []).filter(e => watchlist.includes(e.symbol));

    if (!rows.length) {
      container.innerHTML += '<p class="accuracy-empty-note">No upcoming earnings found for your watchlist in the next 30 days.</p>';
      return;
    }
  }

  // Sort by date ascending so nearest events appear first.
  rows = [...rows].sort((a, b) => (a.date || '').localeCompare(b.date || ''));

  const table = document.createElement('table');
  table.className = 'accuracy-table';
  table.innerHTML = `
    <thead>
      <tr>
        <th>Symbol</th>
        <th>Date</th>
        <th>Session</th>
        <th>EPS Est.</th>
      </tr>
    </thead>
    <tbody>
      ${rows.slice(0, 100).map(e => `
        <tr>
          <td><strong>${_esc(e.symbol || '')}</strong></td>
          <td>${_esc(e.date || '—')}</td>
          <td>${_esc((e.hour || '').toUpperCase() || '—')}</td>
          <td>${e.epsEstimate != null ? Number(e.epsEstimate).toFixed(2) : '—'}</td>
        </tr>
      `).join('')}
    </tbody>
  `;
  container.appendChild(table);
}

