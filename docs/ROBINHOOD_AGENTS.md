# Robinhood Agents Integration (Preparation)

Nostradamus does **not** place live orders yet. This document describes the
handoff layer built for [Robinhood Agents](https://robinhood.com) (or any
external executor) to consume validated trade intents.

## Architecture

```
Predictor v3 → Investor v3 → decisions.json
                              ↓
                   generate_trade_signals.py
                              ↓
              data/trading/robinhood_manifest.json
                              ↓
              Robinhood Agent (external) executes
                              ↓
              POST /api/trading/ack  (fill confirmation)
```

## Prerequisites

1. Nightly pipeline has run: `scripts/orchestrator.py` or `scripts/nightly.ps1`
2. Local server optional: `python scripts/serve.py --port 4174`
3. Environment:

```bash
# Paper / manifest-only (default — safe)
BROKER_MODE=manifest_only

# When Robinhood Agents is wired for live execution
BROKER_MODE=robinhood_agents
BROKER_MAX_GROSS_EXPOSURE=0.90
BROKER_MAX_POSITION_FRAC=0.20
BROKER_MIN_PROBA=0.60
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/trading/manifest` | Orders + risk envelope (Robinhood-ready JSON) |
| GET | `/api/trading/signals` | Raw intents + metadata |
| GET | `/api/trading/config` | Broker mode and limits |
| POST | `/api/trading/generate` | Rebuild manifest from latest `decisions.json` |
| POST | `/api/trading/ack` | Record fill/reject from external agent |
| POST | `/api/orchestrator/run` | Full prep pipeline (skip heavy predictor retrain) |

### Manifest schema (`nostradamus.trading.manifest/v1`)

```json
{
  "schema": "nostradamus.trading.manifest/v1",
  "dryRun": true,
  "brokerTarget": "robinhood_agents",
  "portfolio": { "valueUsd": 10000, "cashAvailableUsd": 8500 },
  "risk": { "maxGrossExposure": 0.9, "minProba": 0.6 },
  "orders": [
    {
      "order_id": "uuid",
      "symbol": "NVDA",
      "side": "buy",
      "order_type": "market",
      "quantity": 12.5,
      "notional_usd": 2500,
      "metadata": { "proba_up": 0.72, "edge": 0.04 }
    }
  ]
}
```

### Ack payload

```json
{
  "order_id": "uuid-from-manifest",
  "status": "filled",
  "filled_qty": 12.5,
  "filled_notional": 2500.0,
  "avg_price": 200.0,
  "broker": "robinhood_agents"
}
```

## Local commands

```powershell
# Full prep (feeds → macro → regime → investor → signals)
python scripts/orchestrator.py --skip-train-predictor

# Trade manifest only
python scripts/generate_trade_signals.py

# Retrain predictor with regime features (heavy)
python scripts/fetch-regime-data.py
python scripts/train-predictor-v3.py
python scripts/train-investor-v3.py
```

## Congressional trade overlay

Politician disclosures (Pelosi, Tuberville, etc.) flow into every manifest order:

1. `fetch-congress-trades.py` → `data/congress/signals_by_symbol.json`
2. `enrich_congress_decisions.py` tags each investor pick
3. `generate_trade_signals.py` boosts notional and adds `metadata.congress`

See `docs/CONGRESS_TRADES.md`.

## Data sources powering predictions

| Source | Role |
|--------|------|
| yfinance / Tiingo / Alpha Vantage | Equity OHLCV fallback chain |
| FRED (12 series) | Macro regime (VIX, spreads, HY OAS, unemployment, CPI, …) |
| GDELT 2.0 | Daily market news tone |
| FinBERT | Per-pick headline sentiment (enrich step) |

## Safety gates before going live

1. `data/feeds/health.json` → `criticalReady: true`
2. Investor backtest `summary.json` → positive return with `min_proba ≥ 0.60`
3. `BROKER_MODE=manifest_only` until Robinhood Agent is tested on paper
4. Profit gate on paper agent still negative — do not auto-scale live size

## Files

- `scripts/broker/adapter.py` — broker abstraction
- `scripts/generate_trade_signals.py` — manifest builder
- `data/trading/robinhood_manifest.json` — latest export
- `data/trading/execution_log.jsonl` — ack audit trail
