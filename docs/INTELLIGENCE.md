# Nostradamus Perpetual Intelligence

## Modules

| Module | Script | Output |
|--------|--------|--------|
| Mass psychology | `scripts/intelligence/mass_psychology.py` | `data/mass_psychology/` |
| Insider monitor | `scripts/intelligence/insider_monitor.py` | `data/insider/fed_monitor_alerts.json` |
| Execution feedback | `scripts/intelligence/execution_feedback.py` | `data/trading/forward_portfolio.json` |
| Forward IC | `scripts/intelligence/forward_score.py` | `data/accuracy/v3_live_ic.json` |
| Champion sync | `scripts/intelligence/champion_sync.py` | `data/intelligence/live_champion_overlay.json` |
| Risk engine | `scripts/intelligence/risk_engine.py` | enforced on manifests |
| Brain | `scripts/intelligence/brain.py` | `data/intelligence/brain_status.json` |
| **Unified score** | `scripts/intelligence/unified_score.py` | composite per symbol (all paths) |

## Unified score (all traders)

`unified_score.composite_score()` blends:

- Predictor v3 (`pred_proba_up`, `pred_ret`) — already trained with regime/congress/insider overlays
- Live congress signals (incl. watchlist / Pelosi weighting)
- Insider monitor (public Form 4)
- Mass psychology (Reddit/RSS)
- Optional Penny ML head on Penny desk scan

Used by: **trader arena**, **generate_trade_signals** (long + short), **penny_engine**, **daytrader_engine**.

Weights: `config/trading_policy.json` → `unifiedScore.weights`. Disable: `UNIFIED_SCORE_ENABLED=false`.

## Legal / honest use

- **Insider monitor** uses **public SEC Form 4** filings only. It does not detect illegal pre-disclosure trading. Following disclosed insider clusters is legal with filing delay; **not guaranteed profit**.
- **Mass psychology** scrapes public Reddit/RSS — retail mood, not insider information.
- **Live trading** remains blocked until `nostradamus-live` gate is green.

## API

- `GET /api/intelligence/status`
- `POST /api/intelligence/pulse`

## Autonomous

`continual_intelligence.ps1` runs every 2h via `autonomous_loop.ps1`.
