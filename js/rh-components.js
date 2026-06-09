/**
 * Reusable drill-down UI primitives (progressive disclosure).
 */

export function fmt(value, kind) {
  if (value == null || Number.isNaN(value)) return '—';
  const n = Number(value);
  switch (kind) {
    case 'pct': return `${(n * 100).toFixed(1)}%`;
    case 'pctRaw': return `${n.toFixed(1)}%`;
    case 'pctSigned': return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
    case 'num2': return n.toFixed(2);
    case 'num3': return n.toFixed(3);
    case 'num4': return n.toFixed(4);
    case 'int': return n.toLocaleString();
    case 'usd': return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
    case 'usd2': return `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    default: return String(value);
  }
}

/** Segmented tab strip — returns HTML string */
export function tabStrip(id, tabs, activeId) {
  return `<div class="td-tabs" id="${id}" role="tablist">
    ${tabs.map((t) => `
      <button type="button" class="td-tabs__btn${t.id === activeId ? ' td-tabs__btn--active' : ''}"
        role="tab" data-tab="${t.id}" aria-selected="${t.id === activeId}">
        ${t.icon ? `<span class="td-tabs__icon">${t.icon}</span>` : ''}${t.label}
      </button>`).join('')}
  </div>`;
}

/** Bind tab clicks; panels use data-panel="{id}" */
export function bindTabs(root, onChange) {
  const buttons = root.querySelectorAll('[data-tab]');
  buttons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.tab;
      buttons.forEach((b) => {
        const on = b.dataset.tab === id;
        b.classList.toggle('td-tabs__btn--active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      root.querySelectorAll('[data-panel]').forEach((p) => {
        p.hidden = p.dataset.panel !== id;
      });
      onChange?.(id);
    });
  });
}

/** Compact KPI — tap to expand explanation */
export function drillKpi({ id, label, value, tone = 'neutral', tag = '', detail = '' }) {
  const hasDetail = !!detail;
  return `<div class="td-drill td-drill--${tone}">
    <button type="button" class="td-drill__head" ${hasDetail ? `data-drill="${id}" aria-expanded="false"` : 'disabled'}>
      <span class="td-drill__label">${label}${tag ? `<span class="td-drill__tag">${tag}</span>` : ''}</span>
      <span class="td-drill__value td-drill__value--${tone}">${value}</span>
      ${hasDetail ? '<span class="td-drill__chev">›</span>' : ''}
    </button>
    ${hasDetail ? `<div class="td-drill__body" id="drill-${id}" hidden><p>${detail}</p></div>` : ''}
  </div>`;
}

export function bindDrills(root) {
  root.querySelectorAll('[data-drill]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const el = root.querySelector(`#drill-${btn.dataset.drill}`);
      if (!el) return;
      const open = el.hidden;
      el.hidden = !open;
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.querySelector('.td-drill__chev')?.classList.toggle('td-drill__chev--open', open);
    });
  });
}

/** Collapsible section with summary row */
export function accordionSection({ id, title, summary, bodyHtml, open = false }) {
  return `<details class="td-acc" id="${id}" ${open ? 'open' : ''}>
    <summary class="td-acc__sum">
      <span class="td-acc__title">${title}</span>
      <span class="td-acc__hint">${summary || ''}</span>
    </summary>
    <div class="td-acc__body">${bodyHtml}</div>
  </details>`;
}

/** Horizontal dock tile for module navigation */
export function dockTile(m) {
  const warn = m.tone === 'warn' ? ' td-dock__tile--warn' : '';
  return `<button type="button" class="td-dock__tile${warn}" data-route="${m.route}">
    <span class="td-dock__icon">${m.icon}</span>
    <span class="td-dock__name">${m.title}</span>
    <span class="td-dock__stat">${m.stat || ''}</span>
  </button>`;
}

/** Chart card wrapper */
export function chartCard(title, subtitle, canvasId, height = 200) {
  return `<div class="td-chart-card">
    <div class="td-chart-card__head">
      <h3 class="td-chart-card__title">${title}</h3>
      ${subtitle ? `<p class="td-chart-card__sub">${subtitle}</p>` : ''}
    </div>
    <div class="td-chart-card__canvas" style="height:${height}px">
      <canvas id="${canvasId}"></canvas>
    </div>
  </div>`;
}
