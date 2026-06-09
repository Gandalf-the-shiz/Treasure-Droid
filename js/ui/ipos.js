import { escapeHtml as esc } from "../utils/helpers.js";
import { loadTickerRegistry } from "../api/manager.js";

const IPO_DATA_PATH = "./data/ipos/upcoming.json";

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function toPct(value) {
  return `${(value * 100).toFixed(1)}%`;
}

function buildSectorSentiment(predictions = [], tickerMap = new Map()) {
  const bySector = new Map();

  for (const p of predictions) {
    const info = tickerMap.get(p.symbol);
    const sector = info?.sector || "Other";
    const signed = (Number(p.probability) || 0.5) - 0.5;
    if (!bySector.has(sector)) bySector.set(sector, []);
    bySector.get(sector).push(signed);
  }

  const out = new Map();
  for (const [sector, vals] of bySector.entries()) {
    const avg = vals.reduce((s, v) => s + v, 0) / Math.max(vals.length, 1);
    out.set(sector, avg);
  }
  return out;
}

function computeIpoPrediction(ipo, sectorSignal, marketSignal) {
  const sector = Number(sectorSignal) || 0;
  const market = Number(marketSignal) || 0;

  // A conservative blend: sector + broad market + deal quality proxy.
  const sizeB = Number(ipo.expectedDealSizeUsdBn || 0);
  const underwriterTier = Number(ipo.underwriterTier || 2); // 1 best, 3 weakest

  const dealQuality = clamp((sizeB / 3) - (underwriterTier - 1) * 0.12, -0.25, 0.25);
  const momentum = (sector * 0.55) + (market * 0.25) + (dealQuality * 0.20);

  const probability = clamp(0.5 + momentum, 0.35, 0.78);
  const direction = probability >= 0.5 ? "UP" : "DOWN";

  // Confidence is intentionally capped for IPOs due to sparse history.
  const confidence = clamp(0.52 + Math.abs(momentum) * 1.1, 0.52, 0.86);

  return {
    direction,
    probability,
    confidence,
  };
}

function riskBadge(riskLevel) {
  const level = String(riskLevel || "high").toLowerCase();
  if (level === "low") return "🟢 Low";
  if (level === "medium") return "🟡 Medium";
  return "🔴 High";
}

export async function renderIpoView(container, appState) {
  container.innerHTML = "";

  const title = document.createElement("h2");
  title.className = "backtest-title";
  title.textContent = "🚀 Upcoming IPOs + Directional Forecast";
  container.appendChild(title);

  const note = document.createElement("p");
  note.className = "heatmap-demo-note";
  note.textContent = "IPO predictions are probabilistic and high-risk; confidence is intentionally capped until post-listing data exists.";
  container.appendChild(note);

  let payload;
  try {
    const res = await fetch(IPO_DATA_PATH);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    payload = await res.json();
  } catch (err) {
    container.innerHTML += `<p class="accuracy-empty-note">Could not load IPO dataset (${esc(err.message)}).</p>`;
    return;
  }

  const ipos = Array.isArray(payload?.ipos) ? payload.ipos : [];
  if (!ipos.length) {
    container.innerHTML += '<p class="accuracy-empty-note">No upcoming IPO entries available right now.</p>';
    return;
  }

  const tickerMap = await loadTickerRegistry();
  const preds = appState?.v2Predictions?.items || [];
  const sectorSentiment = buildSectorSentiment(preds, tickerMap);

  const marketSignal = preds.length
    ? preds.reduce((s, p) => s + ((Number(p.probability) || 0.5) - 0.5), 0) / preds.length
    : 0;

  const rows = ipos
    .map(ipo => {
      const sector = ipo.sector || "Other";
      const sectorSignal = sectorSentiment.get(sector) || 0;
      const pred = computeIpoPrediction(ipo, sectorSignal, marketSignal);

      return {
        ...ipo,
        ...pred,
      };
    })
    .sort((a, b) => String(a.expectedDate).localeCompare(String(b.expectedDate)));

  const table = document.createElement("table");
  table.className = "accuracy-table";
  table.innerHTML = `
    <thead>
      <tr>
        <th>Company</th>
        <th>Ticker</th>
        <th>Expected Date</th>
        <th>Sector</th>
        <th>Pred.</th>
        <th>Prob.</th>
        <th>Confidence</th>
        <th>Risk</th>
      </tr>
    </thead>
    <tbody>
      ${rows.map(r => `
        <tr>
          <td><strong>${esc(r.company || "—")}</strong></td>
          <td>${esc(r.symbol || "TBD")}</td>
          <td>${esc(r.expectedDate || "TBD")}</td>
          <td>${esc(r.sector || "Other")}</td>
          <td>${r.direction === "UP" ? "📈 UP" : "📉 DOWN"}</td>
          <td>${toPct(r.probability)}</td>
          <td>${toPct(r.confidence)}</td>
          <td>${riskBadge(r.riskLevel)}</td>
        </tr>
      `).join("")}
    </tbody>
  `;
  container.appendChild(table);

  const meta = document.createElement("p");
  meta.className = "accuracy-empty-note";
  meta.textContent = `Dataset updated: ${payload.updatedAt || "unknown"} • Sources: ${Array.isArray(payload.sources) ? payload.sources.join(", ") : "manual + CI"}`;
  container.appendChild(meta);
}
