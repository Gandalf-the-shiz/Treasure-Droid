let _accuracyChart = null;
let _calibrationChart = null;

const BASELINE = 52;
const RETRAIN_THRESHOLD = 53;

export function initAccuracyDashboard() {
  const container = document.getElementById('view-accuracy');
  if (!container) return;
  container.innerHTML = '<div class="accuracy-panel"><h2 class="accuracy-panel__title">📊 Prediction Accuracy</h2><p class="accuracy-empty-note">Loading server-side accuracy data…</p></div>';
  void _render(container);
}

async function _render(container) {
  const log = await _fetchJSON('./data/accuracy/accuracy-log.json');
  if (!log || !Array.isArray(log.entries) || log.entries.length === 0) {
    container.innerHTML = `
      <div class="accuracy-panel">
        <h2 class="accuracy-panel__title">📊 Prediction Accuracy</h2>
        <p class="accuracy-empty-note">Accuracy data will appear after the first \`accuracy.yml\` run completes.</p>
      </div>`;
    return;
  }

  const entries = log.entries
    .filter(e => e && e.date)
    .sort((a, b) => a.date.localeCompare(b.date));
  const validEntries = entries.filter(e => typeof e.hitRate === 'number');
  const roll7 = _rollingWeighted(entries, 7);
  const roll30 = _rollingWeighted(entries, 30);
  const roll90 = _rollingWeighted(entries, 90);
  const roll7Days = _windowDataDays(entries, 7);
  const roll30Days = _windowDataDays(entries, 30);
  const roll90Days = _windowDataDays(entries, 90);

  const dailyReports = new Map();
  await Promise.all(validEntries.map(async e => {
    const d = await _fetchJSON(`./data/accuracy/${e.date}.json`);
    if (d) dailyReports.set(e.date, d);
  }));

  const diagnostics = _computeDiagnostics(entries, dailyReports);
  const walkForward = await _loadLatestWalkForward();

  const panel = document.createElement('div');
  panel.className = 'accuracy-panel';
  panel.innerHTML = `
    <h2 class="accuracy-panel__title">📊 Prediction Accuracy</h2>
    <div class="accuracy-metrics">
      ${_metricCard('7-Day', _fmtPct(roll7), _rollingWindowSubtext(roll7Days, 7, 'Directional accuracy'))}
      ${_metricCard('30-Day', _fmtPct(roll30), _rollingWindowSubtext(roll30Days, 30, 'Auto-retrain threshold: 53%'))}
      ${_metricCard('90-Day', _fmtPct(roll90), _rollingWindowSubtext(roll90Days, 90, 'Long-term directional accuracy'))}
      ${_metricCard('Regression MAE', diagnostics.regressionMAE != null ? `${(diagnostics.regressionMAE * 100).toFixed(2)}%` : '—', 'Predicted return vs realized return')}
    </div>
    <div class="accuracy-section">
      <h3 class="accuracy-section__title">Daily Accuracy vs 52% Baseline</h3>
      ${validEntries.length < 30 ? `<p class="accuracy-empty-note">Only ${validEntries.length} days of accuracy data so far. Chart will fill in over the coming weeks as the daily \`accuracy.yml\` workflow runs.</p>` : ''}
      <div id="accuracy-chart-container" class="accuracy-chart-container"></div>
    </div>
    <div class="accuracy-metrics">
      ${_metricCard('TP', String(diagnostics.confusion.tp), 'Predicted UP, actual UP')}
      ${_metricCard('TN', String(diagnostics.confusion.tn), 'Predicted DOWN, actual DOWN')}
      ${_metricCard('FP', String(diagnostics.confusion.fp), 'Predicted UP, actual DOWN')}
      ${_metricCard('FN', String(diagnostics.confusion.fn), 'Predicted DOWN, actual UP')}
    </div>
    <div class="accuracy-section">
      <h3 class="accuracy-section__title">Confidence Calibration (Deciles)</h3>
      <div id="calibration-chart-container" class="accuracy-chart-container"></div>
    </div>
    ${walkForward ? `
      <div class="accuracy-section">
        <h3 class="accuracy-section__title">Walk-Forward Validation (Latest)</h3>
        <p class="accuracy-empty-note">
          Folds: ${walkForward.aggregated?.folds ?? 0} · Accuracy: ${_fmtPct(walkForward.aggregated?.accuracy)} ·
          AUC: ${_fmtNum(walkForward.aggregated?.auc)} · Regression MAE: ${walkForward.aggregated?.regressionMAE != null ? `${(walkForward.aggregated.regressionMAE * 100).toFixed(2)}%` : '—'}
        </p>
      </div>` : ''}
  `;
  container.innerHTML = '';
  container.appendChild(panel);

  _renderAccuracyChart(entries);
  _renderCalibrationChart(diagnostics.calibration);
}

function _metricCard(label, value, sub) {
  return `
    <div class="accuracy-metric-card">
      <span class="accuracy-metric-card__label">${label}</span>
      <span class="accuracy-metric-card__value">${value}</span>
      <span class="accuracy-metric-card__sub">${sub}</span>
    </div>
  `;
}

function _rollingWeighted(entries, days) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  let total = 0;
  let correct = 0;
  for (const e of entries) {
    if (typeof e.hitRate !== 'number') continue;
    if (new Date(`${e.date}T00:00:00Z`) < cutoff) continue;
    const n = Number(e.total || 0);
    if (!n) continue;
    total += n;
    correct += Number(e.correct || 0);
  }
  return total > 0 ? correct / total : null;
}

function _windowDataDays(entries, days) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  return entries.filter(e => typeof e.hitRate === 'number' && new Date(`${e.date}T00:00:00Z`) >= cutoff).length;
}

function _rollingWindowSubtext(actualDays, expectedDays, fallback) {
  if (actualDays >= expectedDays) return fallback;
  const missing = expectedDays - actualDays;
  return `based on ${actualDays} of ${expectedDays} days — needs ~${missing} more days for a stable estimate`;
}

function _computeDiagnostics(entries, dailyReports) {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 30);

  const detail = [];
  const reg = [];
  for (const e of entries) {
    if (new Date(`${e.date}T00:00:00Z`) < cutoff) continue;
    const daily = dailyReports.get(e.date);
    if (!daily) continue;
    if (typeof daily?.metrics?.regressionMAE === 'number') reg.push(daily.metrics.regressionMAE);
    for (const r of (daily.detail || [])) {
      detail.push(r);
      if (typeof r.regressionAbsError === 'number') reg.push(r.regressionAbsError);
    }
  }

  const confusion = { tp: 0, tn: 0, fp: 0, fn: 0 };
  const buckets = new Map();
  for (let lo = 0.5; lo < 1; lo += 0.1) buckets.set(lo.toFixed(1), { total: 0, hit: 0 });

  for (const r of detail) {
    if (r.predicted === 'UP' && r.actual === 'UP') confusion.tp += 1;
    else if (r.predicted === 'DOWN' && r.actual === 'DOWN') confusion.tn += 1;
    else if (r.predicted === 'UP' && r.actual === 'DOWN') confusion.fp += 1;
    else if (r.predicted === 'DOWN' && r.actual === 'UP') confusion.fn += 1;

    const c = Number(r.confidence);
    if (!Number.isFinite(c) || c < 0.5) continue;
    const lo = Math.min(0.9, Math.floor(c * 10) / 10).toFixed(1);
    const b = buckets.get(lo);
    if (!b) continue;
    b.total += 1;
    if (Number(r.correct) === 1) b.hit += 1;
  }

  const calibration = Array.from(buckets.entries()).map(([lo, b]) => {
    const lower = Number(lo);
    const upper = Number((lower + 0.1).toFixed(1));
    const mid = (lower + upper) / 2;
    return {
      label: `${lo}–${upper.toFixed(1)}`,
      expected: mid,
      actual: b.total ? b.hit / b.total : null,
    };
  });

  const regressionMAE = reg.length ? reg.reduce((s, v) => s + v, 0) / reg.length : null;
  return { confusion, calibration, regressionMAE };
}

function _renderAccuracyChart(entries) {
  if (typeof Chart === 'undefined') return;
  const el = document.getElementById('accuracy-chart-container');
  if (!el) return;
  if (_accuracyChart) _accuracyChart.destroy();
  const canvas = document.createElement('canvas');
  el.innerHTML = '';
  el.appendChild(canvas);

  const labels = entries.map(e => e.date);
  const daily = entries.map(e => typeof e.hitRate === 'number' ? e.hitRate * 100 : null);
  const rolling30 = entries.map((_, i) => {
    const slice = entries.slice(Math.max(0, i - 29), i + 1).filter(e => typeof e.hitRate === 'number');
    if (!slice.length) return null;
    return (slice.reduce((s, e) => s + e.hitRate, 0) / slice.length) * 100;
  });
  const belowThreshold = rolling30.map(v => (v != null && v < RETRAIN_THRESHOLD ? v : null));

  _accuracyChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Daily accuracy %', data: daily, borderColor: 'rgba(124,111,239,1)', backgroundColor: 'rgba(124,111,239,0.15)', fill: true, tension: 0.25 },
        { label: '30-day rolling %', data: rolling30, borderColor: 'rgba(38,217,127,1)', backgroundColor: 'transparent', tension: 0.25, borderWidth: 2 },
        { label: '52% baseline', data: labels.map(() => BASELINE), borderColor: 'rgba(255,255,255,0.45)', borderDash: [6, 4], pointRadius: 0 },
        { label: 'Below 53% threshold', data: belowThreshold, borderColor: 'rgba(240,92,110,0.9)', backgroundColor: 'rgba(240,92,110,0.18)', fill: { target: { value: RETRAIN_THRESHOLD } }, pointRadius: 0, tension: 0.2 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100, ticks: { callback: v => `${v}%` } } },
    },
  });
}

function _renderCalibrationChart(calibration) {
  if (typeof Chart === 'undefined') return;
  const el = document.getElementById('calibration-chart-container');
  if (!el) return;
  if (_calibrationChart) _calibrationChart.destroy();
  const canvas = document.createElement('canvas');
  el.innerHTML = '';
  el.appendChild(canvas);

  _calibrationChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: calibration.map(b => b.label),
      datasets: [
        {
          label: 'Actual hit rate',
          data: calibration.map(b => (b.actual != null ? b.actual * 100 : null)),
          borderColor: 'rgba(124,111,239,1)',
          backgroundColor: 'rgba(124,111,239,0.15)',
          tension: 0.2,
        },
        {
          label: 'Perfect calibration',
          data: calibration.map(b => b.expected * 100),
          borderColor: 'rgba(255,255,255,0.45)',
          borderDash: [5, 4],
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100, ticks: { callback: v => `${v}%` } } },
    },
  });
}

async function _loadLatestWalkForward() {
  const now = new Date();
  for (let i = 0; i < 12; i++) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const tag = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
    const report = await _fetchJSON(`./data/accuracy/walk-forward-${tag}.json`);
    if (report) return report;
  }
  return null;
}

async function _fetchJSON(path) {
  try {
    const r = await fetch(path, { cache: 'no-store' });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function _fmtPct(v) {
  return v == null ? '—' : `${(v * 100).toFixed(1)}%`;
}

function _fmtNum(v) {
  return Number.isFinite(v) ? Number(v).toFixed(3) : '—';
}
