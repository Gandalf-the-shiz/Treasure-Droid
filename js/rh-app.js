/**
 * Nostradamus Robinhood-style SPA router.
 */
import { openPageHelp } from './rh-help.js';
import { renderHome } from './rh-pages/home.js';
import { renderMarkets } from './rh-pages/markets.js';
import { renderInvestorPage } from './rh-pages/investor-page.js';
import { renderTrade } from './rh-pages/trade.js';
import { renderStock } from './rh-pages/stock.js';
import { renderArchitecture } from './rh-pages/architecture.js';
import { renderPredictions } from './rh-pages/predictions.js';
import { renderPenny } from './rh-pages/penny.js';
import { renderArena } from './rh-pages/arena.js';
import { renderMegamind } from './rh-pages/megamind.js';
import { renderFleet } from './rh-pages/fleet.js';
import { initStarfield } from './rh-starfield.js';

const TITLES = {
  home: 'Treasure Droid',
  markets: 'Markets',
  investor: 'Investor',
  trade: 'Trade',
  predictions: 'Bounties',
  penny: 'Penny Wolf',
  stock: 'Stock',
  architecture: 'Stack & Edge',
  arena: 'Investor Arena',
  megamind: 'Treasure Droid · Captain',
  fleet: 'The Fleet',
};

let currentPage = 'home';
/** Bumps on each navigation; stale async renders bail out after await. */
let renderSeq = 0;

function parseRoute() {
  const hash = (location.hash || '#/home').replace(/^#\/?/, '');
  const parts = hash.split('/').filter(Boolean);
  if (parts[0] === 'stock' && parts[1]) {
    return { page: 'stock', symbol: parts[1].toUpperCase() };
  }
  if (parts[0] === 'architecture') {
    const sub = ['compare', 'brain'].includes(parts[1]) ? parts[1] : 'system';
    return { page: 'architecture', sub };
  }
  if (parts[0] === 'arena') {
    const version = /^v\d+$/i.test(parts[1] || '') ? parts[1].toLowerCase() : null;
    const traderId = version && parts[2] ? parts[2] : null;
    return { page: 'arena', version, traderId };
  }
  if (parts[0] === 'megamind') {
    const qs = (location.hash.split('?')[1] || '');
    const highlight = new URLSearchParams(qs).get('highlight');
    return { page: 'megamind', highlight };
  }
  if (parts[0] === 'fleet') {
    return { page: 'fleet', agentId: parts[1] || null };
  }
  if (parts[0] === 'chat') {
    return { page: 'megamind' };
  }
  const page = ['home', 'markets', 'investor', 'trade', 'predictions', 'penny', 'arena', 'megamind', 'fleet', 'architecture'].includes(parts[0]) ? parts[0] : 'home';
  return { page };
}

function setActiveTab(page) {
  document.querySelectorAll('.rh-tab').forEach((tab) => {
    const r = tab.dataset.route;
    const active = r === page || (page === 'stock' && r === 'markets')
      || (page === 'arena' && r === 'arena')
      || (page === 'megamind' && r === 'megamind')
      || (page === 'architecture' && r === 'architecture');
    tab.classList.toggle('rh-tab--active', active && ['home', 'markets', 'investor', 'trade', 'predictions', 'penny', 'arena', 'megamind', 'fleet', 'architecture'].includes(r));
    tab.toggleAttribute('aria-current', active && tab.classList.contains('rh-tab--active') ? 'page' : false);
  });
}

function navigate(page, symbol) {
  if (page === 'stock' && symbol) {
    location.hash = `#/stock/${symbol}`;
  } else if (page === 'architecture') {
    location.hash = symbol === 'compare' ? '#/architecture/compare'
      : symbol === 'brain' ? '#/architecture/brain' : '#/architecture';
  } else {
    location.hash = `#/${page}`;
  }
}

async function render() {
  const seq = ++renderSeq;
  const route = parseRoute();
  const main = document.getElementById('rh-main');
  const titleEl = document.getElementById('rh-page-title');
  if (!main) return;

  currentPage = route.page === 'stock' ? 'stock' : route.page;
  titleEl.textContent = route.page === 'stock'
    ? route.symbol
    : route.page === 'arena' && route.traderId != null
      ? `Arena ${route.version} #${route.traderId}`
      : route.page === 'arena' && route.version
        ? `Arena ${route.version}`
        : (TITLES[route.page] || 'Treasure Droid');
  setActiveTab(route.page);
  document.body.classList.toggle('td-body--arch', route.page === 'architecture' && route.sub !== 'compare');

  const stale = () => seq !== renderSeq;

  if (route.page === 'home') {
    await renderHome(main);
    if (stale()) return;
  } else if (route.page === 'markets') {
    await renderMarkets(main, { navigate });
    if (stale()) return;
  } else if (route.page === 'investor') {
    await renderInvestorPage(main);
    if (stale()) return;
  } else if (route.page === 'trade') {
    await renderTrade(main);
    if (stale()) return;
  } else if (route.page === 'predictions') {
    await renderPredictions(main);
    if (stale()) return;
  } else if (route.page === 'penny') {
    await renderPenny(main);
    if (stale()) return;
  } else if (route.page === 'arena') {
    await renderArena(main, route, stale);
    if (stale()) return;
  } else if (route.page === 'megamind') {
    await renderMegamind(main, route);
    if (stale()) return;
  } else if (route.page === 'fleet') {
    await renderFleet(main, route, stale);
    if (stale()) return;
  } else if (route.page === 'stock') {
    await renderStock(main, route.symbol);
    if (stale()) return;
  } else if (route.page === 'architecture') {
    await renderArchitecture(main, route);
    if (stale()) return;
  } else {
    await renderHome(main);
  }
}

function init() {
  document.querySelectorAll('.rh-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      navigate(tab.dataset.route);
    });
  });

  document.getElementById('rh-help-btn')?.addEventListener('click', () => {
    const route = parseRoute();
    const pid = route.page === 'stock' ? 'stock' : route.page;
    openPageHelp(pid);
  });

  document.getElementById('rh-arch-btn')?.addEventListener('click', () => {
    navigate('architecture');
  });

  window.addEventListener('hashchange', () => render());
  if (!location.hash) location.hash = '#/home';
  initStarfield();
  render();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
