/**
 * Shared Chart.js helpers for Treasure Droid SPA.
 * Requires Chart.js loaded globally (index.html CDN).
 */

const GOLD = '#f5c542';
const PROFIT = '#2dd4a7';
const LOSS = '#e85d4a';
const MUTED = 'rgba(154, 163, 192, 0.35)';
const GRID = 'rgba(90, 110, 170, 0.12)';

export function destroyChart(chart) {
  if (chart) chart.destroy();
  return null;
}

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(11, 16, 32, 0.94)',
        borderColor: 'rgba(245, 197, 66, 0.35)',
        borderWidth: 1,
        titleFont: { family: 'JetBrains Mono, monospace', size: 11 },
        bodyFont: { size: 12 },
      },
    },
    scales: {
      x: {
        grid: { color: GRID },
        ticks: { color: '#9aa3c0', maxTicksLimit: 8, font: { size: 10 } },
      },
      y: {
        grid: { color: GRID },
        ticks: { color: '#9aa3c0', font: { size: 10 } },
      },
    },
    ...extra,
  };
}

/** Equity / index line chart */
export function renderLineChart(canvas, { labels, values, label = 'Equity', color = PROFIT, fill = true }) {
  if (!canvas || !window.Chart || !values?.length) return null;
  const stroke = color.startsWith('#') ? color : PROFIT;
  const fillColor = fill
    ? (stroke === PROFIT ? 'rgba(45, 212, 167, 0.12)' : stroke === LOSS ? 'rgba(232, 93, 74, 0.1)' : 'rgba(245, 197, 66, 0.1)')
    : false;

  return new window.Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label,
        data: values,
        borderColor: stroke,
        backgroundColor: fillColor,
        borderWidth: 2,
        pointRadius: values.length > 40 ? 0 : 2,
        tension: 0.28,
        fill: !!fill,
      }],
    },
    options: baseOptions(),
  });
}

/** Horizontal bar chart (sleeve IC, metrics) */
export function renderBarChart(canvas, { labels, values, colors }) {
  if (!canvas || !window.Chart || !values?.length) return null;
  const cols = colors || values.map((v) => (v >= 0 ? PROFIT : LOSS));
  return new window.Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: cols,
        borderRadius: 4,
        maxBarThickness: 28,
      }],
    },
    options: baseOptions({
      indexAxis: 'y',
      scales: {
        x: { grid: { color: GRID }, ticks: { color: '#9aa3c0', font: { size: 10 } } },
        y: { grid: { display: false }, ticks: { color: '#eaeaf2', font: { size: 11 } } },
      },
    }),
  });
}

/** Tiny sparkline on canvas (fleet cards) */
export function renderSparkline(canvas, values, { color } = {}) {
  if (!canvas || !window.Chart || (values?.filter((v) => v != null).length || 0) < 2) return null;
  const up = values[values.length - 1] >= values[0];
  const stroke = color || (up ? PROFIT : LOSS);
  return new window.Chart(canvas, {
    type: 'line',
    data: {
      labels: values.map((_, i) => i),
      datasets: [{
        data: values,
        borderColor: stroke,
        borderWidth: 1.5,
        pointRadius: 0,
        tension: 0.35,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: {
        x: { display: false },
        y: { display: false },
      },
      animation: false,
    },
  });
}

export { GOLD, PROFIT, LOSS, MUTED };
