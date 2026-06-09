/**
 * js/ui/export.js
 * CSV export functionality — Phase 6.
 *
 * Exports all stored predictions from the prediction tracker as a
 * downloadable CSV file. The user triggers this via an "Export CSV"
 * button shown in the Accuracy Dashboard view.
 *
 * CSV columns:
 *   symbol, prediction_date, predicted_direction, predicted_change,
 *   predicted_price, current_price_at_prediction, actual_price,
 *   actual_direction, is_correct, price_error, confidence, is_demo
 *
 * Dependencies: js/ml/tracker.js
 */

import { getPredictions } from '../ml/tracker.js';

// ─── Public API ───────────────────────────────────────────────

/**
 * Build a CSV string from all stored predictions and trigger a
 * browser file download.
 *
 * @param {string} [filename='nostradamus-predictions.csv']
 */
export function exportPredictionsCSV(filename = 'nostradamus-predictions.csv') {
  const predictions = getPredictions();

  if (predictions.length === 0) {
    return { success: false, message: 'No predictions to export.' };
  }

  const csv = _buildCSV(predictions);
  _triggerDownload(csv, filename, 'text/csv;charset=utf-8;');
  return { success: true, count: predictions.length };
}

// ─── Private helpers ──────────────────────────────────────────

/**
 * CSV column headers.
 * @type {string[]}
 */
const CSV_HEADERS = [
  'symbol',
  'prediction_date',
  'predicted_direction',
  'predicted_change',
  'predicted_price',
  'current_price_at_prediction',
  'actual_price',
  'actual_direction',
  'is_correct',
  'price_error',
  'confidence',
  'is_demo',
];

/**
 * Convert an array of TrackedPrediction objects to a CSV string.
 *
 * @param {import('../ml/tracker.js').TrackedPrediction[]} predictions
 * @returns {string}
 */
function _buildCSV(predictions) {
  const rows = [CSV_HEADERS.join(',')];

  for (const p of predictions) {
    const date = p.generatedAt
      ? new Date(p.generatedAt).toISOString().slice(0, 10)
      : '';
    const delta = p.delta != null ? p.delta.toFixed(2) : '';
    const predictedPrice = p.predictedPrice != null ? p.predictedPrice.toFixed(2) : '';
    const currentPrice   = p.currentPrice   != null ? p.currentPrice.toFixed(2)   : '';
    const actualPrice    = p.actualPrice    != null ? p.actualPrice.toFixed(2)     : '';
    const priceError     = p.priceError     != null ? p.priceError.toFixed(2)      : '';
    const confidence     = p.confidence     != null ? (p.confidence * 100).toFixed(1) : '';

    const row = [
      _csvCell(p.symbol),
      _csvCell(date),
      _csvCell(p.direction),
      _csvCell(delta),
      _csvCell(predictedPrice),
      _csvCell(currentPrice),
      _csvCell(actualPrice),
      _csvCell(p.actualDirection ?? ''),
      _csvCell(p.isCorrect != null ? (p.isCorrect ? 'TRUE' : 'FALSE') : ''),
      _csvCell(priceError),
      _csvCell(confidence),
      _csvCell(p.isDemo ? 'TRUE' : 'FALSE'),
    ];
    rows.push(row.join(','));
  }

  return rows.join('\r\n');
}

/**
 * Wrap a value in CSV-safe quotes, escaping any internal quotes.
 *
 * @param {string|number} value
 * @returns {string}
 */
function _csvCell(value) {
  const str = String(value ?? '');
  if (str.includes(',') || str.includes('"') || str.includes('\n')) {
    return `"${str.replace(/"/g, '""')}"`;
  }
  return str;
}

/**
 * Trigger a browser file download with the given content.
 *
 * @param {string} content  - File content string
 * @param {string} filename
 * @param {string} mimeType
 */
function _triggerDownload(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url  = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href     = url;
  link.download = filename;
  link.style.display = 'none';
  document.body.appendChild(link);
  link.click();
  // Clean up
  setTimeout(() => {
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, 100);
}
