/**
 * Per-page help content and modal.
 */

export const PAGE_HELP = {
  home: {
    title: 'The Oracle',
    sections: [
      { heading: 'Command center', body: 'Health ring, navigation to every realm, model breakdown, and data-flow status.' },
      { heading: 'Realms', body: 'Tap a card to jump to Markets, Arena, Megamind, Prophecy, Penny, and more.' },
      {
        heading: 'Health score',
        body: 'The ring shows the percentage of checks passing. Gold rows are healthy; red rows need attention.',
      },
      {
        heading: 'Refresh',
        body: 'Data auto-refreshes when the continuous brain runs. Revisit after market open for the latest pulse.',
      },
    ],
  },
  markets: {
    title: 'Markets — Live ML Rankings',
    sections: [
      { heading: 'Search', body: 'Type a ticker symbol to open its detail page with price chart and news.' },
      { heading: 'Top picks', body: 'Sorted by ML edge score from Predictor v3 live inference (800-symbol scan). Tap any row for details.' },
      { heading: 'Edge', body: 'Edge = (probability up − 0.5) × 2 × |predicted return|. Higher means stronger model conviction.' },
    ],
  },
  investor: {
    title: 'Investor Agent',
    sections: [
      { heading: 'Purpose', body: 'Shows day-by-day fake-dollar portfolio decisions from Investor v3 trained on Predictor outputs.' },
      { heading: 'Playback', body: 'Use the day slider or Play to walk through historical picks, allocations, and realised P&L.' },
      { heading: 'Retrain', body: 'Retrain Investor runs train-investor-v3.py on the server (several minutes). Decisions.json updates when complete.' },
    ],
  },
  trade: {
    title: 'Trade — Robinhood Handoff',
    sections: [
      { heading: 'Swing manifest', body: 'Top-K overnight/swing positions from Investor v3. External Robinhood Agents poll GET /api/trading/manifest.' },
      { heading: 'Daytrade manifest', body: 'Intraday aggressive orders refreshed every 15 minutes during market hours.' },
      { heading: 'Congress', body: 'Notable politician trades (Pelosi watchlist, etc.) that boost investor ranking when aligned.' },
      { heading: 'Generate', body: 'Regenerate buttons re-run signal scripts without a full harness cycle.' },
    ],
  },
  stock: {
    title: 'Stock Detail',
    sections: [
      { heading: 'Quote', body: 'Latest close from local historical bars (or live fetch via server).' },
      { heading: 'Chart', body: '90-day price history from /api/bars.' },
      { heading: 'News', body: 'Yahoo RSS headlines via /api/news with optional FinBERT sentiment cache.' },
    ],
  },
  architecture: {
    title: 'System Architecture',
    sections: [
      { heading: 'Diagram', body: 'Interactive map of data sources, training jobs, and Robinhood handoff paths. See docs/GLORIOUS_STACK.md for ops runbook.' },
    ],
  },
  megamind: {
    title: 'Megamind',
    sections: [
      { heading: 'What it is', body: 'Meta-agent analyzing Investor Arena v1/v2 and intelligence feeds. Proposes improvements — not live trade orders.' },
      { heading: 'Approve', body: 'Approval writes LATEST_APPROVED.md and queues Cursor Agent work for Cursor to implement.' },
      { heading: 'Email', body: 'Pending recommendations appear in the 5:30 PM daily email with approve links (localhost).' },
    ],
  },
  arena: {
    title: 'Investor Arena',
    sections: [
      { heading: 'v1 vs v2', body: '200 simulated traders: v1 uses strict threshold gates; v2 ranks the full ML panel. Returns are simulated from pred_ret, not live fills.' },
      { heading: 'Drill-down', body: 'Tap a version card for the full leaderboard, then any row for daily P&L, trades, portfolio, genome, and reasoning.' },
      { heading: 'Ultimate Model', body: 'Meta-agent report at the bottom — recommends pipeline and selection improvements (research only).' },
    ],
  },
  penny: {
    title: 'Penny Wolf',
    sections: [
      { heading: 'Desk', body: 'Sub-$5 momentum sleeve with ML heat map. Paper only until forward edge is proven.' },
      { heading: 'Pulse', body: 'Run desk pulse refreshes scan and simulated book on the server.' },
    ],
  },
  predictions: {
    title: 'Prophecy Markets',
    sections: [
      { heading: 'Separate sleeve', body: 'Kalshi/Polymarket paper bets — independent bankroll from the stock book.' },
      { heading: 'Each bet', body: 'Expand a row for your chosen side, model vs market math, and estimated expected profit at entry (not guaranteed).' },
      { heading: 'Portfolio', body: 'Summary metrics, exchange breakdown, open positions, and recent resolves.' },
    ],
  },
};

export function openPageHelp(pageId) {
  const doc = PAGE_HELP[pageId] || PAGE_HELP.home;
  const root = document.getElementById('rh-modal-root');
  if (!root) return;

  const backdrop = document.createElement('div');
  backdrop.className = 'rh-modal-backdrop';
  backdrop.setAttribute('role', 'dialog');
  backdrop.setAttribute('aria-label', doc.title);

  let html = `<div class="rh-modal"><h2>${doc.title}</h2>`;
  for (const s of doc.sections) {
    html += `<h3>${s.heading}</h3><p>${s.body}</p>`;
  }
  html += `<p style="margin-top:20px"><a href="#/architecture">View full architecture diagram</a></p>`;
  html += `<button type="button" class="rh-btn-primary" style="width:100%;margin-top:16px" id="rh-help-close">Close</button></div>`;
  backdrop.innerHTML = html;
  root.appendChild(backdrop);

  const close = () => backdrop.remove();
  backdrop.querySelector('#rh-help-close')?.addEventListener('click', close);
  backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { close(); document.removeEventListener('keydown', esc); }
  });
}
