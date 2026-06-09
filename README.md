# 🔮 Nostradamus V2 — The Market Intelligence Engine

> **Treasure Droid ? autonomous treasure-hunting AI for the markets.** _Mining the markets for buried treasure._

> ?? **This project rebranded to Treasure Droid and evolved well beyond the legacy "Nostradamus V2" static app described in the historical sections below.** It is now a **local, always-on autonomous trading-research stack** (FastAPI backend + ML fleet + an AI captain). **The authoritative, current document is [`docs/HANDOFF.md`](docs/HANDOFF.md) ? read that first.**

## ????? Treasure Droid (current system)

A rusty robot-pirate **captain** (AI meta-agent) commands a **fleet of ML trading agents** that walk forward on paper ? each documenting its portfolio, trade history, and the ML reasoning behind every pick. Many weak, uncorrelated **alpha sleeves** are neutralized and combined into a market-neutral book. **Live capital is gated** behind proven forward edge.

**Read these (in order):**
- [`docs/HANDOFF.md`](docs/HANDOFF.md) ? **start here**: full state, architecture maps, what works / what doesn't, file index, how to run.
- [`docs/ALPHA_DOCTRINE.md`](docs/ALPHA_DOCTRINE.md) + [`docs/UNGODLY.md`](docs/UNGODLY.md) ? the strategy (Fundamental Law: IC � ?breadth � ?).
- [`docs/UNIFIED_ARCHITECTURE.md`](docs/UNIFIED_ARCHITECTURE.md) ? fleet-of-sleeves + captain unification plan.
- [`docs/MEGA_YACHT.md`](docs/MEGA_YACHT.md) ? live execution tracker � [`docs/HOSTING.md`](docs/HOSTING.md) � [`docs/SOUND_SMART.md`](docs/SOUND_SMART.md) (glossary).

**Quick start (local):**
```bash
python scripts/serve.py --host 127.0.0.1 --port 8000   # dashboard + JSON API
```
Public: **https://treasure-droid.com** (Cloudflare Tunnel ? this machine; public is read-only, action endpoints blocked).

**Architecture in one line:** data feeds ? Predictor v3 ? `live.csv` ? neutralized alpha sleeves ? market-neutral book + **the Crew** (forward-paper agents) ? **Treasure Droid** captain monitors/spawns/allocates ? execution behind the readiness gate.

**Honest status:** the machinery is solid; forward paper P&L is still negative, so **live trading is correctly blocked** until forward edge is proven. See `docs/HANDOFF.md` �2 and �9.

---

### ?? Legacy Nostradamus V2 notes (historical reference only)

> The sections below predate the Treasure Droid rebrand and the autonomous backend. Kept for history; for anything current, trust `docs/HANDOFF.md`.

---

## Description

**Nostradamus** is an AI-powered stock prediction platform using a Bidirectional LSTM with Monte Carlo Dropout uncertainty estimation. It analyzes the entire US stock market (~7,000+ tickers) and generates daily directional predictions (UP/DOWN) with calibrated confidence scores.

**Architecture at a glance:**
- **Dual-head BiLSTM model** — simultaneous classification (P(UP)) + regression (% return) outputs
- **3-API fallback system** — Finnhub → Twelve Data → Polygon.io, with token-bucket rate limiting
- **Automated CI/CD pipeline** — 9 GitHub Actions workflows for data, features, training, predictions, and accuracy scoring
- **IPO intelligence pipeline** — scheduled upcoming IPO ingestion + directional IPO forecasting view
- **Monte Carlo Dropout** — 20 stochastic forward passes for calibrated uncertainty estimates
- **100% static frontend** — runs on GitHub Pages, no server required

---

## Getting Started

**Run locally:** Just open `index.html` in a browser (or serve with any static file server). No build step needed.

**Demo mode:** The app works without any API keys. It loads pre-generated predictions and historical data from the repo.

**Add API keys:** Open the Settings panel in the app and enter your keys. They are stored in `localStorage` and never sent to any server other than the respective API providers. See `.env.example` for which keys to get and where.

### Run With Real Training Data (Not Demo)

Use the full public-data training pipeline, then generate fresh predictions:

```bash
python scripts/pretrain-full-year.py
python scripts/generate-predictions.py
```

Serve the app from the repo root and open it in your browser:

```bash
python -m http.server 4173
```

Then open:

```text
http://127.0.0.1:4173/index.html
```

This makes the UI read from committed real datasets in `data/historical/` and current generated predictions in `data/predictions/`.

### Paper Investing Agent (2nd ML Model)

Nostradamus now includes a separate online-learning paper agent model that does not replace the main up/down predictor.

Run it with a $10,000 starting bankroll:

```bash
python scripts/paper-agent.py
```

Outputs:

- `data/paper_agent/summary.json`
- `data/paper_agent/equity_curve.csv`
- `data/paper_agent/daily_metrics.csv`
- `data/paper_agent/trades.csv`
- `data/paper_agent/profit-gate.json`
- `models/v2/paper_agent_model.joblib`

Tune + gate it for profit-first behavior:

```bash
python scripts/tune-paper-agent.py
python scripts/paper-agent.py
python scripts/paper-agent-profit-gate.py
```

The profit gate can automatically reduce risk in `data/paper_agent/agent-config.json`
if drawdown/return conditions degrade.

---

## API Keys

All keys are **optional** — the app works in demo mode without any. See `.env.example` for details.

| Provider | Free Tier | Use |
|---|---|---|
| [Finnhub](https://finnhub.io/register) | 60 calls/min | Real-time quotes, WebSocket streaming (primary) |
| [Twelve Data](https://twelvedata.com/pricing) | 800 calls/day, 8 calls/min | Quotes and time series (secondary fallback) |
| [Polygon.io](https://polygon.io/pricing) | Unlimited (prev-day only) | Previous-close data (tertiary fallback) |

The nightly historical data pipeline (`fetch-history.py`) uses **yfinance** which requires **no API key**.

---

## Automated Data Pipeline

```
Weekly  (Sun 00:00 UTC):   fetch-tickers.py  → data/tickers/us_tickers.json
Nightly (Mon-Fri 21:30):   fetch-history.py  → data/historical/*.json
Nightly (Mon-Fri 22:00):   build-features.py → data/features/*.json
Nightly (Mon-Fri 22:30):   generate-predictions.py → data/predictions/YYYY-MM-DD.json
Nightly (Mon-Fri 23:55):   score-accuracy.py → data/accuracy/accuracy-log.json
Nightly (Mon-Fri 00:20):   paper-agent-optimize.yml → tune + simulate + profit gate
Weekdays (Mon-Fri 12:20):  fetch-ipos.py → data/ipos/upcoming.json
Weekly  (Sun 04:00 UTC):   auto-retrain (if accuracy < 53%) → models/v2/
Daily   (09:15 UTC):       verify-data-feeds.py → data/feeds/health.json
```

---

## Data Feeds — The Canal That Powers Both Models

Both the prediction model and the paper-investing agent are only as good as
the data feeding them. The repo ships with a vendor-agnostic adapter layer
that lets us add, swap, or fall back between data providers without rewiring
the rest of the pipeline.

### Live components

| File | Purpose |
|---|---|
| `scripts/data_sources.py` | Layered adapter: `fetch_equity_history()`, `fetch_macro_series()`, `fetch_gdelt_daily_tone()`, `probe_providers()`. |
| `scripts/fetch-history-multiyear.py` | Multi-year OHLCV backfill (`--years N`) that merges into the existing sector-chunked schema. |
| `scripts/verify-data-feeds.py` | Daily live probe of every provider, writes `data/feeds/health.json` + 90-day history. |
| `.github/workflows/verify-data-feeds.yml` | Scheduled health check (09:15 UTC) with commit-back. |

### Verified working today

| Provider | Use | Status | Key required |
|---|---|---|---|
| **yfinance** | Adjusted daily OHLCV (primary equity) | ✅ live | No |
| **FRED CSV** | Macro series (DFF, T10Y2Y, VIXCLS, UMCSENT, …) | ✅ live | No |
| **GDELT 2.0 DOC** | Daily news/event tone aggregates | ✅ live (rate-limited) | No |
| **Stooq bulk ZIP** | Delisted-tolerant deep history (10y+) | ⚠️ manual one-shot — see below | Captcha (manual) |

#### Stooq: why it's manual

Every programmatic Stooq endpoint — per-symbol CSV, regional CSV, and the
ASCII regional ZIP dump — is now captcha-walled. There is no API key signup
(the "Get your apikey" text is just a captcha gate). The only reliable way
to get the data is a one-time manual download:

1. Open <https://stooq.com/db/h/?b=d_us_txt> in a browser.
2. Click the `us` row (≈508 MB), solve the captcha, save `d_us_txt.zip`.
3. Feed it to the importer (years of delisted-safe history, no rate limits):
   ```powershell
   python scripts/import-stooq-bulk-zip.py --zip "C:/path/to/d_us_txt.zip" --years 10
   ```

The verifier skips Stooq's live probe when no key is set, so it no longer
marks the canal red over a wall we can't autonomously breach.

### Data feeds upgrade TODO

Priority order — top to bottom is "build the canal wider before deepening it":

1. **Bulk historical depth** — run `scripts/import-stooq-bulk-zip.py` once against the manually-downloaded `d_us_txt.zip` for 10 years of delisted-tolerant OHLCV across the full US universe.
2. **Real keyed fallback for live refresh** — add an Alpha Vantage or Tiingo adapter to `data_sources.py` (both have instant-signup free tiers; no captcha). This replaces the role Stooq was supposed to play in the daily refresh path.
3. **Free macro/point-in-time** — extend `fetch-macro.py` to pull ALFRED vintages (point-in-time releases) so the model never trains on data it could not have known. Series to add: `T10Y3M`, `BAMLH0A0HYM2` (HY OAS), `UNRATE`, `CPIAUCSL`, `INDPRO`.
4. **News + event sentiment** — wire `fetch_gdelt_daily_tone()` into `build-features.py` as a market-regime feature (rolling 5-day avg tone Δ vs baseline). Add per-ticker keyword queries for the top 200 by market cap.
5. **Paid upgrades when budget allows** — Polygon (intraday), EODHD (fundamentals + delistings), Nasdaq Data Link / Quandl. The adapter signature already supports plugging these in without touching downstream scripts.
6. **Institutional-grade (long-term)** — CRSP / WRDS or Norgate for survivorship-bias-free history. These require licensing; integration is a one-day swap once licensed because the adapter returns the same candle shape.
7. **Symbol-mastering** — add a CUSIP/FIGI mapping table so symbol changes, mergers, and ticker recycles don't corrupt long-horizon training.
8. **Cost & slippage model** — push the paper agent's per-trade cost/slippage assumptions into config so backtests reflect real broker frictions.
9. **Continuous health gate** — extend `verify-data-feeds.py` so a failed `criticalReady` flag blocks `auto-retrain.yml` and `paper-agent-optimize.yml` from running on rotten inputs.

### Operator quick-reference

```powershell
# Probe every provider once and write data/feeds/health.json
python scripts/verify-data-feeds.py

# Backfill 10 years for a handful of symbols (smoke test)
python scripts/fetch-history-multiyear.py --tickers AAPL MSFT NVDA --years 10

# Backfill 5 years for the top 500 tickers from the registry
python scripts/fetch-history-multiyear.py --years 5 --limit 500
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Vanilla HTML/CSS/JS (no framework, no build step) |
| **Charting** | Chart.js (CDN) |
| **ML (browser)** | TensorFlow.js (CDN) |
| **ML (training)** | Python + Keras/TensorFlow + tensorflowjs_converter |
| **Data** | Python + yfinance + pandas + ta (technical indicators) |
| **CI/CD** | GitHub Actions (9 workflows) |
| **Hosting** | GitHub Pages |

---

## Project Overview

**Nostradamus V2** is no longer a 5-stock demo. V2 analyzes the **ENTIRE US stock market** (~7,000+ tickers across NYSE, NASDAQ, AMEX). The goal is to build a money-making machine that uses ML to predict price direction with enough accuracy to generate actionable alpha.

- **Live URL**: https://gandalf-the-shiz.github.io/Nostradamus/
- **Repo**: https://github.com/Gandalf-the-shiz/Nostradamus
- **Built entirely by GitHub Agents** — all coding happens via PRs opened from Issues
- **No server required** — 100% static frontend, CI/CD handles all heavy computation

**Core principle: Unlimited compute, zero excuses.** We design around every bottleneck and limitation.

---

## V1 Autopsy — What We're Fixing

| # | Issue | Severity | Root Cause | V2 Solution |
|---|---|---|---|---|
| 1 | Starter model weights are empty (0 bytes) | 🔴 Critical | `weights.bin` never generated, `weightsManifest: []` | New Phase 1: Build offline training pipeline that generates real pre-trained weights from full market data |
| 2 | Historical data directory is empty | 🔴 Critical | `FINNHUB_API_KEY` secret never configured; only 5 hardcoded tickers | New data pipeline: scrape entire market via yfinance + SEC EDGAR, commit compressed datasets to repo |
| 3 | Only 5 hardcoded symbols (AAPL, GOOGL, MSFT, AMZN, TSLA) | 🔴 Critical | `fetch-historical.js` has `const SYMBOLS = ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA']` | Build universal ticker registry from SEC EDGAR (~7,000+ tickers), fetch history for ALL |
| 4 | Accuracy log has never recorded anything | 🟡 Major | CI workflow writes heartbeats only; real metrics are client-side only | Server-side accuracy computation in GitHub Actions using committed predictions vs actual prices |
| 5 | Retraining version recording uses blind 5-min setTimeout | 🟡 Major | `scheduledTrain()` is fire-and-forget | Refactor to use async/await with proper completion callback, record version only after training resolves |
| 6 | Single shared model for all stocks | 🟡 Major | One set of weights in localStorage overwritten per training | V2 uses a universal model trained on normalized cross-market data; per-sector fine-tuned variants |
| 7 | Confidence score is synthetic (not calibrated) | 🟡 Major | `Math.abs(pred - current) * 5` clamped to [0.5, 0.95] | Implement Monte Carlo dropout for real uncertainty estimation; calibrate with Platt scaling |
| 8 | No test suite | 🟡 Major | Zero test files | Add comprehensive test suite: unit tests for preprocessing math, integration tests for API fallback, ML pipeline validation |
| 9 | `Math.min(...values)` stack overflow on large arrays | 🟡 Major | Spread operator limit ~100K args | Replace with iterative `reduce()` for min/max in `preprocessing.js` |
| 10 | Prediction resolution timing is immediate, not next-day | 🟡 Major | Resolves on any fresh price, not next trading day close | Implement proper T+1 resolution: predictions resolve only after the next market close |
| 11 | Training data only comes from `sample.json` or live API | 🟡 Major | No committed historical dataset to bootstrap from | Build massive committed dataset via GitHub Actions data pipeline |
| 12 | No sentiment analysis (news exists but not used in ML features) | 🟠 Medium | News module renders headlines but doesn't feed NLP features to model | Add sentiment scoring pipeline that feeds into feature matrix |
| 13 | No fundamental data features (P/E, EPS, earnings dates) | 🟠 Medium | Model only sees price/volume technicals | Add fundamental indicators as features from free APIs |

---

## V2 Architecture Overview

| Layer | Technology | Change from V1 |
|---|---|---|
| **Hosting** | GitHub Pages | Same |
| **Frontend** | Vanilla HTML/CSS/JS | Same |
| **Charting** | Chart.js (CDN) | Same |
| **ML Engine** | TensorFlow.js (CDN) | **Upgraded model: Bidirectional LSTM (128→64), 30-day sliding window, 33 features, binary classification** |
| **Ticker Registry** | SEC EDGAR `company_tickers_exchange.json` | **NEW: ~7,000+ US exchange tickers auto-updated weekly** |
| **Historical Data Pipeline** | GitHub Actions + Python (`yfinance`) | **NEW: Bulk download all tickers, compress to JSON, commit to repo** |
| **Pre-trained Model** | GitHub Actions + Python (`tensorflow/keras`) | **NEW: Server-side training on full market, export TF.js model to `models/`** |
| **Primary API** | Finnhub | Same |
| **Secondary API** | Twelve Data | Same |
| **Tertiary API** | Polygon.io | Same |
| **NEW: Quaternary API** | Alpha Vantage | **NEW: 25 calls/day free, technical indicators endpoint** |
| **Data Persistence** | localStorage + IndexedDB | **UPGRADED: IndexedDB for large datasets (model weights, historical data)** |
| **CI/CD** | GitHub Actions | **UPGRADED: 9 workflows (deploy, fetch-tickers, fetch-history, build-features, train-model, generate-predictions, accuracy, auto-retrain, weekly-report)** |

### Why These APIs?
GitHub Pages serves files with no backend proxy. All API calls happen directly from the user's browser, so **CORS support is mandatory**. Finnhub, Twelve Data, and Polygon.io all support CORS from browser clients.

> **Note on Alpha Vantage:** Alpha Vantage does NOT support CORS and **cannot be called from the browser**. It is used exclusively in GitHub Actions (server-side Python scripts) for enriching feature data during training — never in the browser JS.

### API Key Strategy
- API keys are **entered by the user** in the app's Settings panel and stored in `localStorage`
- Keys are never hardcoded in the source
- If no API key is configured, the app runs in **Demo Mode** loading from committed historical data

---

## Rate Limit Strategy

| Technique | Description |
|---|---|
| **Request Batching** | Batch multiple symbol lookups into one API call where possible |
| **localStorage Cache + TTL** | Don't re-fetch data within 5-minute windows; store with expiry timestamp |
| **Staggered / Lazy Loading** | Only fetch data for stocks currently visible in the viewport |
| **Exponential Backoff** | On API errors (429, 5xx), retry with increasing delay |
| **Fallback Chain** | Finnhub → Twelve Data → Polygon.io → cached data → demo data |
| **Committed Historical Data** | Historical OHLCV comes from committed dataset, not live API calls — eliminates rate limit bottleneck entirely |

---

## Free Data Source Strategy — Zero-Cost Full Market Coverage

### 1. SEC EDGAR Ticker Registry
**URL:** https://www.sec.gov/files/company_tickers_exchange.json

- Free, no API key, no rate limit, updated daily by the SEC
- Contains ticker, CIK, company name, and exchange for all US-listed companies
- GitHub Actions workflow fetches weekly, commits to `data/tickers/us_tickers.json`
- Filter to NYSE, NASDAQ, AMEX exchanges only (remove OTC/pink sheets)

### 2. yfinance (Yahoo Finance) for Historical OHLCV
- Free, no API key required, no official rate limit (but must throttle)
- Can bulk download full history for any US ticker
- GitHub Actions workflow runs nightly, fetches 1 year of daily data for all tickers
- **Strategy:** Fetch in batches of 50 tickers at a time, 2-second delay between batches
- Store as compressed JSON in `data/historical/` (split by sector: `technology.json`, `healthcare.json`, etc.)
- Raw uncompressed size: ~400–500MB (7,000 tickers × 252 days × 5 OHLCV values × ~50 bytes/value). With aggressive JSON compression (gzip/deflate, ~75–80% reduction), this comes down to ~50–100MB. Git LFS is very likely required — configure it before committing historical data.

### 3. Existing APIs (Finnhub, Twelve Data, Polygon.io) for Real-Time Quotes
- Same fallback chain as V1, but now used **only** for live/real-time data
- Historical data comes from the committed dataset, not live API calls
- This eliminates the rate limit bottleneck for historical data entirely

### 4. Alpha Vantage (New Quaternary Fallback — CI Only)
- Free API key, 25 calls/day
- Valuable for: RSI, MACD, Bollinger Bands, SMA/EMA pre-computed
- Used in GitHub Actions for enriching feature data during training
- **Never called from the browser** (no CORS support)

---

## The 10-Phase Execution Plan

> **Agents: update these checkboxes in every PR before merging.**

### ✅ Phase 1: V1 Foundation (COMPLETE — inherited from V1)
- [x] Repository structure, GitHub Pages, CI/CD
- [x] Frontend scaffold (HTML/CSS/JS, mobile-first)
- [x] API integration modules (Finnhub, Twelve Data, Polygon.io)
- [x] localStorage cache with TTL
- [x] Demo mode with sample.json
- [x] Chart.js and TensorFlow.js CDN integration

### Phase 2: Universal Ticker Registry
- [x] Create `scripts/fetch-tickers.py` — downloads SEC EDGAR `company_tickers_exchange.json`
- [x] Filter to NYSE + NASDAQ + AMEX, exclude OTC/test tickers, output to `data/tickers/us_tickers.json`
- [x] Create `.github/workflows/fetch-tickers.yml` — runs weekly (Sunday midnight UTC)
- [x] Update frontend search to use committed ticker list for instant offline autocomplete
- [x] Add sector/industry classification from SEC SIC codes
- [x] Target: ~7,000+ actively traded US tickers

### Phase 3: Full-Market Historical Data Pipeline
- [x] Create `scripts/fetch-history.py` — uses `yfinance` to bulk download 1 year OHLCV for all tickers
- [x] Implement batched downloading: 50 tickers per batch, 2-second inter-batch delay
- [x] Implement retry logic with exponential backoff for failed tickers
- [x] Store data as sector-chunked compressed JSON files in `data/historical/` (e.g., `technology.json`, `healthcare.json`, `financials.json`)
- [x] Add incremental update mode: only fetch new data since last run (don't re-download everything)
- [x] Create `.github/workflows/fetch-history.yml` — runs nightly Mon-Fri at 9:30 PM UTC
- [x] Add data validation: reject tickers with < 100 trading days of data
- [x] Add `data/historical/manifest.json` — metadata file listing all available tickers, date ranges, last update timestamps
- [x] Configure Git LFS for `data/historical/*.json` if total size exceeds 100MB
- [x] Target: 1 year of daily OHLCV data for ~7,000 tickers

### Phase 4: Feature Engineering Pipeline (Server-Side)
- [x] Create `scripts/build-features.py` — reads raw OHLCV, computes full feature matrix
- [x] Implement 15+ features per ticker per day:
  - OHLCV (5 features: open, high, low, close, volume)
  - RSI-14
  - MACD (signal line, histogram)
  - SMA-5, SMA-20, SMA-50, SMA-200
  - EMA-12, EMA-26
  - Bollinger Bands (upper, lower, bandwidth)
  - ATR-14 (Average True Range)
  - OBV (On-Balance Volume)
  - Stochastic Oscillator (%K, %D)
  - Rate of Change (ROC-10)
  - Day-of-week encoding (one-hot, 5 features)
  - Month encoding (cyclical sin/cos, 2 features)
  - 30-day realized volatility
  - 5-day price momentum
  - Volume ratio (current / 20-day average)
- [x] Normalize all features using min-max scaling per-ticker (store scaling params)
- [x] Create windowed sequences: 30-day lookback windows → next-day direction label
- [x] Output to `data/features/` as compressed numpy-compatible JSON
- [x] Add `data/features/scaling_params.json` — global scaling parameters for the model
- [x] Create `.github/workflows/build-features.yml` — runs after fetch-history completes

### Phase 5: Server-Side Model Training (The Real Brain)
- [x] Create `scripts/train-model.py` — full TensorFlow/Keras training pipeline
- [x] Model architecture: **Bidirectional LSTM** (TF.js-compatible)
  - Input: (batch, 30 timesteps, 33 features)
  - Layer 1: Bidirectional LSTM (128 units, return_sequences=True)
  - Layer 2: Dropout (0.3)
  - Layer 3: LSTM (64 units, return_sequences=False)
  - Layer 4: Dropout (0.2)
  - Layer 5: Dense (32, relu)
  - Layer 6: Dropout (0.2)
  - Layer 7: Dense (1, sigmoid) — P(price goes UP tomorrow)
  - Optimizer: Adam (lr=0.001 with ReduceLROnPlateau)
  - Loss: Binary crossentropy
  - Metrics: Accuracy, AUC, Precision, Recall
- [x] Training strategy:
  - Train/validation/test split: 70% / 15% / 15% (time-series aware — no future leakage)
  - Class balancing: UP days slightly outnumber DOWN days historically; use class weights
  - Early stopping with patience=10 on validation AUC
  - Save best model checkpoint (restore_best_weights=True)
- [x] Export trained model to TensorFlow.js format using `tensorflowjs_converter`
  - Output to `models/v2/model.json` + binary weight shards
  - Also export `models/v2/metadata.json` with training date, accuracy, feature list, scaling params
- [x] Create `.github/workflows/train-model.yml` — runs weekly (Sunday at 3 AM UTC after build-features)
- [x] Log training metrics to `data/training-logs/` (loss curves, confusion matrix, per-sector accuracy)
- [ ] Target: >55% directional accuracy on held-out test set (note: the true random baseline is ~52% because US markets trend up more days than down historically; the model must beat the naive "always predict UP" baseline, not just 50%)
- [ ] Stretch goal: >60% accuracy with sector-specific fine-tuning

### Phase 6: Upgraded Browser ML Engine
- [x] Update `js/ml/model.js` to load new V2 model architecture
- [x] Update `js/ml/preprocessing.js`:
  - Replace `Math.min(...spread)` with iterative `reduce()` min/max
  - Support all 33 features matching the server-side pipeline
  - Load scaling params from `models/v2/metadata.json`
- [x] Update `js/ml/prediction.js`:
  - Implement Monte Carlo dropout (run prediction N=20 times with dropout enabled, average results)
  - Calculate real confidence intervals from the MC dropout distribution
  - Replace synthetic confidence with calibrated probability
- [x] Update `js/ml/training.js`:
  - Proper async/await completion tracking (fix the 5-min setTimeout hack)
  - `scheduledTrain()` now returns a Promise
- [x] Update `js/ml/tracker.js`:
  - Implement proper T+1 resolution: predictions resolve only at next market close
  - `getNextTradingDay()` helper skips weekends
- [ ] Implement Transfer Learning: browser loads pre-trained base model, user can fine-tune on their watchlist stocks
- [x] Migrate model weight storage from localStorage to IndexedDB (support models >5MB) — `js/storage/indexeddb.js` created

### Phase 7: Full-Market Dashboard Overhaul
- [x] Replace 5-stock dashboard with full-market views:
  - **Market Heatmap**: Treemap visualization of all sectors/stocks by prediction strength (like finviz.com) — `js/ui/heatmap.js` ✅
  - **Top Predictions**: Ranked list of stocks with strongest UP/DOWN signals + highest confidence ✅
  - **Sector Rotation**: Show which sectors the model is most bullish/bearish on ✅
  - **Momentum Scanner**: Stocks with strongest technical momentum alignment ✅
  - **Earnings Calendar**: Upcoming earnings dates with pre-earnings predictions
- [x] Add stock screener with filters — `js/ui/screener.js` ✅:
  - Prediction direction (UP/DOWN)
  - Confidence threshold (>60%, >70%, >80%)
  - Sector filter
  - Market cap filter
  - Volume filter
- [x] Pagination and virtual scrolling for 7,000+ ticker list
- [x] Lazy-load stock cards as user scrolls (IntersectionObserver)

### Phase 8: Sentiment & Alternative Data
- [x] Integrate Finnhub company news into ML feature pipeline
- [x] Build simple client-side sentiment scorer (`js/utils/sentiment.js`):
  - Keyword-based scoring from headline text (bullish/bearish word lists)
  - Aggregate daily sentiment score per ticker
  - Feed as additional feature to model
- [x] Track sentiment-prediction correlation in accuracy dashboard — `getSentimentCorrelation()` in `js/ml/accuracy.js` ✅
- [x] Add "Market Mood" indicator to dashboard header (aggregate sentiment) ✅
- [x] Display sentiment badge (😊/😐/😟) + gauge in stock detail modal (`js/ui/detail.js`) ✅

### Phase 9: Backtesting Engine
- [x] Create `js/backtest/engine.js` — full backtesting framework ✅
  - Run model predictions against historical data
  - Simulate portfolio: start with $10,000, buy/sell based on model signals
  - Track: total return, Sharpe ratio, max drawdown, win rate
- [x] Add backtesting UI view — `js/ui/backtest-ui.js` ✅:
  - Date range selector
  - Strategy configuration (confidence threshold, max positions, sector filter)
  - Equity curve chart
  - Trade log table
- [x] Compare strategies: model-only vs buy-and-hold benchmark ✅
- [x] Export backtest results to CSV ✅

### Phase 10: Continuous Intelligence Loop
- [x] Automated daily prediction generation via GitHub Actions
  - After market close: fetch latest prices, run model, generate predictions for next day
  - Commit predictions to `data/predictions/YYYY-MM-DD.json`
  - `scripts/generate-predictions.py` + `.github/workflows/generate-predictions.yml`
- [x] Automated accuracy scoring:
  - After market close: compare previous day's predictions to actual results
  - Commit accuracy report to `data/accuracy/YYYY-MM-DD.json`
  - Track rolling 7-day, 30-day, 90-day accuracy metrics
  - `scripts/score-accuracy.py` + upgraded `.github/workflows/accuracy.yml`
- [x] Model auto-retraining — `.github/workflows/auto-retrain.yml` ✅:
  - If rolling 30-day accuracy drops below 53% (chosen as slightly above the ~52% naive "always UP" baseline, providing a minimal positive-alpha margin), trigger automatic retraining workflow
  - Use latest 6 months of data for retraining
  - Only promote new model if it beats current model on held-out test set
  - `accuracy.yml` now automatically triggers `auto-retrain.yml` when the threshold is breached
- [x] Weekly "Market Intelligence Report" auto-generated ✅:
  - Top 10 predicted movers (up and down)
  - Sector rotation signals
  - Model confidence distribution
  - Accuracy trend chart
  - Committed to `data/reports/weekly/YYYY-WW.json`
  - `scripts/generate-weekly-report.py` + `.github/workflows/weekly-report.yml`

---

## File Structure

```
Nostradamus/
├── index.html
├── README.md                          # THIS FILE — the master plan
├── LICENSE
├── manifest.json
├── sw.js
├── icons/
│   ├── icon-192.svg
│   └── icon-512.svg
├── .github/
│   └── workflows/
│       ├── deploy.yml                 # GitHub Pages deployment
│       ├── fetch-tickers.yml          # Weekly: SEC EDGAR ticker refresh
│       ├── fetch-history.yml          # Nightly: yfinance OHLCV download
│       ├── build-features.yml         # After fetch-history: compute features
│       ├── train-model.yml            # Weekly: full model training
│       ├── generate-predictions.yml   # Weekdays: daily prediction generation
│       ├── accuracy.yml               # Daily: prediction accuracy scoring
│       ├── auto-retrain.yml           # Triggered: retrain if accuracy < 53%
│       └── weekly-report.yml          # Saturday: weekly intelligence report
├── css/
│   └── styles.css
├── js/
│   ├── app.js
│   ├── api/
│   │   ├── finnhub.js
│   │   ├── twelvedata.js
│   │   ├── polygon.js
│   │   └── manager.js
│   ├── ml/
│   │   ├── model.js                   # V2 model architecture loader
│   │   ├── training.js                # Browser-side fine-tuning
│   │   ├── prediction.js              # MC dropout + calibrated confidence
│   │   ├── preprocessing.js           # 15+ feature engineering (browser)
│   │   ├── tracker.js                 # T+1 prediction resolution
│   │   ├── accuracy.js
│   │   ├── versioning.js
│   │   └── retraining.js              # Fixed async completion tracking
│   ├── ui/
│   │   ├── dashboard.js               # Full-market heatmap + top predictions
│   │   ├── charts.js
│   │   ├── stockcard.js
│   │   ├── search.js                  # Offline autocomplete from ticker registry
│   │   ├── detail.js
│   │   ├── watchlist.js
│   │   ├── theme.js
│   │   ├── accuracy-dashboard.js
│   │   ├── sectors.js
│   │   ├── screener.js                # NEW: stock screener with filters
│   │   ├── heatmap.js                 # NEW: treemap market heatmap
│   │   ├── backtest-ui.js             # NEW: backtesting interface
│   │   ├── news.js
│   │   ├── help.js
│   │   ├── share.js
│   │   └── export.js
│   ├── backtest/
│   │   └── engine.js                  # NEW: backtesting engine
│   ├── storage/
│   │   ├── cache.js
│   │   └── indexeddb.js               # NEW: IndexedDB for large data
│   └── utils/
│       ├── helpers.js
│       └── sentiment.js               # NEW: keyword sentiment scorer
│   ├── scripts/                           # Server-side Python scripts (run in CI)
│   ├── fetch-tickers.py               # SEC EDGAR ticker download
│   ├── fetch-history.py               # yfinance bulk OHLCV download
│   ├── build-features.py              # Feature engineering pipeline
│   ├── train-model.py                 # TensorFlow/Keras model training
│   ├── generate-predictions.py        # Daily prediction generation
│   ├── score-accuracy.py              # Compare predictions to actuals
│   ├── generate-weekly-report.py      # Weekly intelligence report aggregation
│   └── requirements.txt               # Python dependencies
├── data/
│   ├── sample.json                    # Demo data (V1 compat)
│   ├── tickers/
│   │   └── us_tickers.json            # All ~7,000+ US exchange tickers
│   ├── historical/
│   │   ├── manifest.json              # Metadata: tickers, date ranges, sizes
│   │   ├── technology.json            # Sector-chunked historical data
│   │   ├── healthcare.json
│   │   ├── financials.json
│   │   ├── consumer_discretionary.json
│   │   ├── consumer_staples.json
│   │   ├── energy.json
│   │   ├── industrials.json
│   │   ├── materials.json
│   │   ├── real_estate.json
│   │   ├── utilities.json
│   │   └── communication_services.json
│   ├── features/
│   │   ├── feature_matrix.json        # Computed features (compressed)
│   │   └── scaling_params.json        # Normalization parameters
│   ├── predictions/
│   │   └── YYYY-MM-DD.json            # Daily prediction files
│   ├── accuracy/
│   │   ├── accuracy-log.json          # Rolling accuracy metrics
│   │   └── YYYY-MM-DD.json            # Daily accuracy reports
│   ├── training-logs/
│   │   └── YYYY-MM-DD.json            # Training run metrics
│   └── reports/
│       └── weekly/
│           └── YYYY-WW.json           # Weekly intelligence reports
├── models/
│   ├── starter/                       # V1 model (deprecated)
│   │   ├── model.json
│   │   └── weights.bin
│   └── v2/                            # V2 pre-trained model
│       ├── model.json                 # TF.js model topology
│       ├── group1-shard1of1.bin       # Model weights (real, trained)
│       └── metadata.json              # Training date, accuracy, features, scaling
└── tests/                             # Test suite
    ├── preprocessing.test.js          # minMaxScale, RSI, MACD, buildFeatureMatrix
    ├── prediction.test.js             # demoPrediction, confidence clamping, MC dropout
    ├── api-manager.test.js            # Fallback chain, cache TTL, error handling
    └── backtest.test.js               # Backtest engine (placeholder stubs)
```

---

## Complete File Inventory (as of PR #13)

### Frontend (js/)
| File | Size | Purpose |
|---|---|---|
| `js/app.js` | ~11KB | Main entry point, navigation, settings, PWA, service worker |
| `js/api/finnhub.js` | ~4.5KB | Finnhub API client (quotes, candles, company news) |
| `js/api/twelvedata.js` | ~3.7KB | Twelve Data API client (fallback) |
| `js/api/polygon.js` | ~3.0KB | Polygon.io API client (fallback) |
| `js/api/manager.js` | ~15.6KB | API orchestrator, fallback chain, caching, demo data |
| `js/ml/model.js` | ~4.7KB | V2 BiLSTM model builder + loader (32 features, IndexedDB) |
| `js/ml/preprocessing.js` | ~18.8KB | 32-feature engineering pipeline (browser-side, matches build-features.py) |
| `js/ml/prediction.js` | ~7.7KB | Monte Carlo Dropout inference, binary classification |
| `js/ml/tracker.js` | ~7.5KB | T+1 prediction storage and resolution |
| `js/ml/training.js` | ~5.4KB | Browser-side training, returns Promise |
| `js/ml/retraining.js` | ~4.4KB | Auto-retrain trigger, async/await completion |
| `js/ml/accuracy.js` | ~9.5KB | Hit-rate, MAE, daily/weekly time-series metrics |
| `js/ml/versioning.js` | ~6.9KB | Model A/B testing, champion/candidate promotion |
| `js/ui/dashboard.js` | ~18.4KB | Top Predictions, Sector Rotation, Momentum Scanner, Market Mood |
| `js/ui/heatmap.js` | ~13.2KB | Canvas treemap market visualization |
| `js/ui/screener.js` | ~15.0KB | Filterable stock table with pagination |
| `js/ui/backtest-ui.js` | ~22.4KB | Backtesting interface with equity curve and trade log |
| `js/ui/charts.js` | ~14.2KB | Chart.js wrapper for price/volume charts |
| `js/ui/stockcard.js` | ~8.1KB | Individual stock card component |
| `js/ui/search.js` | ~12.6KB | Offline autocomplete from ticker registry |
| `js/ui/detail.js` | ~11.6KB | Stock detail modal with sentiment badge |
| `js/ui/watchlist.js` | ~7.1KB | User watchlist management |
| `js/ui/accuracy-dashboard.js` | ~18.4KB | Accuracy charts, sentiment correlation |
| `js/ui/sectors.js` | ~7.7KB | Sector analysis view |
| `js/ui/news.js` | ~9.8KB | News display with sentiment scoring |
| `js/ui/theme.js` | ~2.8KB | Dark/light theme toggle |
| `js/ui/help.js` | ~9.4KB | User guide modal |
| `js/ui/share.js` | ~5.0KB | Social sharing (Web Share API) |
| `js/ui/export.js` | ~4.1KB | CSV export utility |
| `js/backtest/engine.js` | ~16.8KB | Portfolio simulation (Sharpe, drawdown, win rate) |
| `js/storage/cache.js` | ~3.9KB | localStorage cache with TTL |
| `js/storage/indexeddb.js` | ~4KB+ | IndexedDB wrapper for large data |
| `js/utils/helpers.js` | ~6.9KB | Date helpers, toast notifications |
| `js/utils/sentiment.js` | ~4KB+ | Weighted keyword sentiment scorer [-1, +1] |

### Server-Side Scripts (scripts/)
| File | Size | Purpose |
|---|---|---|
| `scripts/fetch-tickers.py` | ~10KB | SEC EDGAR ticker download, SIC→sector mapping |
| `scripts/fetch-history.py` | ~15KB | yfinance bulk OHLCV download, batched, incremental |
| `scripts/build-features.py` | ~16KB | 32-feature engineering with `ta` library |
| `scripts/train-model.py` | ~20KB | BiLSTM training, TF.js export, evaluation |
| `scripts/generate-predictions.py` | ~13KB | Daily prediction generation for all tickers |
| `scripts/score-accuracy.py` | ~13KB | Compare predictions to actuals, rolling metrics |
| `scripts/generate-weekly-report.py` | ~8.7KB | Weekly intelligence report aggregation |
| `scripts/requirements.txt` | 227B | Python dependencies |

### Workflows (.github/workflows/)
| Workflow | Schedule | Purpose |
|---|---|---|
| `deploy.yml` | On push to main | GitHub Pages deployment |
| `fetch-tickers.yml` | Weekly Sunday midnight | SEC EDGAR ticker refresh |
| `fetch-history.yml` | Nightly Mon-Fri 9:30 PM UTC | yfinance OHLCV download |
| `build-features.yml` | After fetch-history | Compute 32-feature matrices |
| `train-model.yml` | Weekly Sunday 3 AM UTC | Full BiLSTM training + TF.js export |
| `generate-predictions.yml` | Weekdays 10:30 PM UTC | Daily prediction generation |
| `accuracy.yml` | Daily 11:55 PM UTC | Score predictions, trigger auto-retrain |
| `auto-retrain.yml` | Triggered by accuracy.yml or manual | Retrain if accuracy < 53% |
| `weekly-report.yml` | Saturday 5 AM UTC | Weekly intelligence report |

### Tests (tests/)
| File | Tests | Purpose |
|---|---|---|
| `tests/preprocessing.test.js` | ~20 tests | minMaxScale, RSI, MACD, buildFeatureMatrix, stack overflow prevention |
| `tests/prediction.test.js` | ~15 tests | demoPrediction structure, confidence clamping, MC dropout |
| `tests/api-manager.test.js` | ~15 tests | Fallback chain, cache TTL, error handling |
| `tests/backtest.test.js` | ~4 stubs | Backtest engine (placeholder for real historical data) |

---

## PR History

| PR | Title | Lines Changed | Key Deliverables |
|---|---|---|---|
| #1 | Phase 1: Scaffold | — | HTML/CSS/JS structure, GitHub Pages |
| #2 | Phase 2: Data Layer | — | API fallback chain (Finnhub→TwelveData→Polygon), caching |
| #3 | Phase 3: Frontend Dashboard | — | Charts, watchlist, search, detail modal, theme |
| #4 | Phase 4: TF.js LSTM Engine | — | V1 model, prediction, preprocessing (7 features) |
| #5 | Phase 5: Self-Learning | — | Tracker, accuracy, versioning, retraining |
| #6 | Phase 6: PWA + Polish | — | Service worker, sectors, news, export, help, sharing |
| #7 | V2 Master Plan | — | README rewrite with 10-phase roadmap |
| #8 | V2 Phase 2: Ticker Registry | — | SEC EDGAR pipeline, SIC→sector mapping |
| #9 | V2 Phase 3: Historical Data | — | yfinance bulk download, incremental updates |
| #10 | V2 Phase 4: Feature Engineering | — | 32-feature pipeline with `ta` library |
| #11 | V2 Phase 5: Model Training | — | BiLSTM (128→64), binary crossentropy, TF.js export |
| #12 | V2 Phase 6 + Partial 8/10 | +2,272 -337 | Browser ML fix (32 features, MC dropout, T+1), generate-predictions.py, score-accuracy.py, tests, sentiment.js, indexeddb.js |
| #13 | V2 Phases 7+8+9+10 Capstone | +3,000+ | Heatmap, screener, backtest engine+UI, Market Mood, sentiment integration, auto-retrain workflow, weekly reports |

---



1. **No build step** — Same as V1. Vanilla JS, ES modules, GitHub Pages.
2. **Mobile-first** — Same as V1. 375px minimum width.
3. **API keys via Settings UI** — Same as V1. Never hardcode API keys. The user enters them in a Settings panel; they are stored in `localStorage`. See `js/storage/cache.js` for the storage API.
4. **Demo mode** — Same as V1, but now demo mode loads from committed historical data instead of tiny `sample.json`.
5. **Graceful degradation** — Same as V1. Every feature should fail gracefully.
6. **README is the contract** — Same as V1. Every PR must update checkboxes and keep this document accurate.
7. **CDN versions** (do not change without testing):
   - TensorFlow.js: `https://cdn.jsdelivr.net/npm/@tensorflow/tfjs@4.22.0/dist/tf.min.js`
   - Chart.js: `https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js`
8. **NEW: Python scripts run in GitHub Actions only** — The `scripts/` directory contains Python code that runs server-side in CI. It is NEVER loaded in the browser. Keep Python and JS code completely separate.
9. **NEW: Git LFS** — If `data/historical/` exceeds 100MB total, configure Git LFS for `.json` files in that directory.
10. **NEW: IndexedDB for large data** — Model weights and large datasets should use IndexedDB, not localStorage (which has a ~5MB limit per origin).
11. **NEW: Feature parity** — The browser-side `preprocessing.js` must compute features IDENTICALLY to the server-side `build-features.py`. Any difference will cause model predictions to be garbage. Validate with `tests/preprocessing.test.js`: feed the same sample OHLCV data through both implementations and assert all output features match within floating-point tolerance (±1e-6). This test must pass before any Phase 5 model is promoted.
12. **NEW: Time-series splitting** — NEVER use random train/test splits for time series data. Always split chronologically. The test set must be strictly AFTER the training set in time.
13. **NEW: The model predicts P(UP)** — Output is sigmoid ∈ [0, 1]. Values > 0.5 = predicted UP, < 0.5 = predicted DOWN. The confidence is the distance from 0.5 (e.g., 0.85 = 85% confident UP, 0.15 = 85% confident DOWN).

---

## Current Status

| Phase | Description | Status |
|---|---|---|
| V1 Phases 1-6 | Foundation, data layer, UI, ML engine, self-learning, PWA | ✅ Complete |
| V2 Phase 2 | Universal Ticker Registry (SEC EDGAR) | ✅ Code complete — workflow needs first manual trigger |
| V2 Phase 3 | Full-Market Historical Data Pipeline | ✅ Code complete — workflow needs first manual trigger |
| V2 Phase 4 | Server-Side Feature Engineering (32 features) | ✅ Code complete — workflow needs first manual trigger |
| V2 Phase 5 | Server-Side BiLSTM Training Pipeline | ✅ Code complete — workflow needs first manual trigger |
| V2 Phase 6 | Upgraded Browser ML Engine | ✅ Complete — BiLSTM, 32 features, MC dropout, T+1, IndexedDB |
| V2 Phase 7 | Full-Market Dashboard Overhaul | ✅ Complete — Heatmap, Screener, Top Predictions, Sector Rotation, Momentum Scanner |
| V2 Phase 8 | Sentiment & Alternative Data | ✅ Complete — sentiment.js utility, detail badge, Market Mood, correlation panel |
| V2 Phase 9 | Backtesting Engine | ✅ Complete — engine.js + full UI with equity curve, trade log, CSV export |
| V2 Phase 10 | Continuous Intelligence Loop | ✅ Complete — daily predictions, accuracy scoring, auto-retrain, weekly reports |

---

## ⚠️ CRITICAL: First-Run Bootstrap — Data Pipeline Has Never Executed

All code and workflows are complete, but the data directories are still empty. The CI/CD workflows have never been triggered. **The app currently runs in demo mode with fake predictions.**

To activate the full pipeline for the first time, manually trigger these workflows IN ORDER via GitHub Actions → workflow_dispatch:

1. **`fetch-tickers.yml`** → Populates `data/tickers/us_tickers.json` (~7K tickers from SEC EDGAR)
2. **`fetch-history.yml`** → Downloads 1 year OHLCV to `data/historical/*.json` (~400MB raw, 50-100MB compressed)
3. **`build-features.yml`** → Computes 32-feature matrices to `data/features/*.json`
4. **`train-model.yml`** → Trains BiLSTM, exports to `models/v2/model.json` + weight shards
5. **`generate-predictions.yml`** → Generates first daily predictions to `data/predictions/`
6. **`accuracy.yml`** → Scores predictions (needs at least 2 days of predictions + actuals)

**Wait for each to complete before triggering the next.** After the first successful run, the scheduled crons handle everything automatically:
- `fetch-tickers.yml`: Weekly (Sunday midnight UTC)
- `fetch-history.yml`: Nightly Mon-Fri (9:30 PM UTC)
- `build-features.yml`: After fetch-history completes
- `train-model.yml`: Weekly (Sunday 3 AM UTC)
- `generate-predictions.yml`: Weekdays (10:30 PM UTC)
- `accuracy.yml`: Daily (11:55 PM UTC)
- `auto-retrain.yml`: Triggered by accuracy.yml when 30-day accuracy < 53%
- `weekly-report.yml`: Saturday (5 AM UTC)

### What Happens After Bootstrap
- `models/v2/` gets real `model.json` + weight shards
- Browser loads pre-trained model instead of falling back to demo predictions
- Heatmap, screener, and top predictions show real ML outputs
- Accuracy dashboard tracks real performance
- Auto-retraining kicks in if accuracy drops
- Weekly intelligence reports auto-generated

---

## Known Remaining Work

| Item | Priority | Notes |
|---|---|---|
| **Trigger data pipeline for first time** | 🔴 Critical | See bootstrap section above. Nothing works until data + model exist. |
| **Git LFS for historical data** | 🟡 High | `data/historical/*.json` will exceed 100MB. Configure Git LFS before first `fetch-history.yml` run. |
| **Validate model accuracy > 55%** | 🟡 High | Can only verify after first training run. If < 55%, tune hyperparameters or add features. |
| **Remove/replace V1 starter model** | 🟡 Medium | `models/starter/weights.bin` is 0 bytes. Either delete or generate a small working model. |
| **Fundamental data features (P/E, EPS)** | 🟠 Low | V1 Autopsy Issue #13. Model only sees technicals. Add from yfinance `info` dict in `build-features.py`. |
| **Transfer Learning (browser fine-tune)** | 🟠 Low | Phase 6 stretch goal. Let users fine-tune on their watchlist stocks. |
| **Earnings Calendar** | ✅ Complete | `📅 Earnings` view reads Finnhub `/calendar/earnings` for watchlist symbols, with demo fallback in `data/sample-earnings.json`. |
| **Market cap filter in screener** | 🟠 Low | Screener exists but market cap data requires API enrichment. |

---

## Accuracy, Improvement, and Live Prices

Nostradamus now uses committed server-side accuracy logs for honest 7/30/90-day directional performance (plus confusion matrix, calibration, regression MAE, and walk-forward diagnostics), archives every trained model snapshot with richer metadata for promotion/rollback traceability, and hardens free-tier live quotes with rotation wiring, provider cooldown health, and short-lived IndexedDB caching. To observe this: open **📊 Accuracy** for the new analytics panels, open **Dashboard** with API keys configured to watch card prices update live, enable `localStorage.nostradamus_debug='1'` to view provider health/cache diagnostics, and open **📅 Earnings** for watchlist earnings dates.

---

## Implementation Priority Order — The Critical Path

**Nothing else matters until we have data and a trained model.** Build in this order:

1. **Phase 2 → Phase 3 → Phase 4 → Phase 5 (DATA PIPELINE)**
   - Tickers → History → Features → Training
   - Without a real trained model, everything downstream is a demo
2. **Phase 6 (Browser ML Upgrade)**
   - Must happen after Phase 5 so the browser can load the real model
3. **Phase 7 (Dashboard Overhaul)**
   - Can start in parallel with Phase 6
4. **Phase 8 (Sentiment) + Phase 9 (Backtesting)**
   - Independent of each other; can be done in parallel after Phase 6
5. **Phase 10 (Continuous Intelligence Loop)**
   - The capstone — wires everything together; requires all prior phases

---

> ⚠️ **Not financial advice.** Nostradamus is a research and educational project. All predictions are experimental ML outputs and should never be used as the sole basis for investment decisions. Past model accuracy does not guarantee future performance.


---

## Local server (FastAPI)

The static front-end (GitHub Pages) is read-only. To run as a local service with on-demand
retraining and a "last refreshed" indicator on the ?? Investor tab, use the FastAPI wrapper.

**Start the server**

```powershell
& "C:/Users/nicho/AppData/Local/Programs/Python/Python311-arm64/python.exe" scripts/serve.py --port 4174
# ? http://127.0.0.1:4174
```

The Investor tab auto-detects the local API (`/api/health`). When detected it switches to
**LIVE** mode and shows a `? Retrain now` button that runs `scripts/train-investor-v3.py`
with the canonical config and reloads `decisions.json` when finished.

**Endpoints**

| Method | Path                     | Purpose                                        |
|--------|--------------------------|------------------------------------------------|
| GET    | `/api/health`            | server info, decisions file mtime, job state  |
| GET    | `/api/decisions`         | serves `data/investor_v3/decisions.json`      |
| POST   | `/api/retrain`           | kicks off training in background              |
| GET    | `/api/retrain/status`    | poll state + last 50 lines of training log    |
| GET    | `/`                      | static front-end (same as today)              |

**Nightly retrain (Windows Task Scheduler)**

```powershell
# one-time setup � schedules weekdays 17:30 local
powershell -ExecutionPolicy Bypass -File scripts\register-nightly-task.ps1

# run it manually any time
Start-ScheduledTask -TaskName "Nostradamus Nightly Retrain"

# remove it
Unregister-ScheduledTask -TaskName "Nostradamus Nightly Retrain" -Confirm:$false
```

Each run writes `logs/nightly-<timestamp>.log`.


---

## ONNX export + NPU acceleration

The investor policy is also exported to **ONNX** alongside the joblib pickle:

```powershell
python scripts/export_onnx.py --bench
# [export] wrote models\v3\investor\policy.onnx (60 KiB)
# [parity] samples=256 max_abs_err=7.45e-09 ok=True
# [bench]  joblib=3.70 ms  onnx-cpu=0.72 ms  speedup=5.11x
```

The ONNX artifact is portable: same file runs in the browser via
`onnxruntime-web` or on the Snapdragon Hexagon NPU via the QNN execution
provider. `scripts/train-investor-v3.py` also writes `policy.onnx` at the end
of every training run (soft-fails if `skl2onnx` is not installed).

### Headline sentiment encoder (FinBERT on ONNX Runtime)

`scripts/sentiment_encoder.py` scores news headlines with a 3-class FinBERT
(positive / negative / neutral) and a signed score in [-1, 1]. The encoder
auto-detects the best ONNX Runtime execution provider in this order:

1. `QNNExecutionProvider` � Snapdragon Hexagon NPU (~45 TOPS)
2. `DmlExecutionProvider` � DirectML GPU/NPU fallback
3. `CPUExecutionProvider` � always available

```powershell
python scripts/sentiment_encoder.py --demo
# first run downloads ~420 MiB FinBERT ONNX to models/sentiment/
# subsequent runs are warm (~50 ms / headline on CPU)
```

The model + vocab are gitignored (see `models/.gitignore`); re-fetch on a fresh
clone by running `--demo` once. Tokenization is pure-Python WordPiece � no Rust
deps required (works on win_arm64 where `tokenizers` / `safetensors` won't
build).
