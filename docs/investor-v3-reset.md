# Investor V3 — status, reset, improve

## What it is

Investor v3 trains a **meta-policy** on Predictor v3 test-window outputs (`data/predictions_v3/test.csv`), then walk-forward simulates a **$10k paper book** with Kelly-style sizing. Outputs:

- `data/investor_v3/decisions.json` — UI source of truth
- `models/v3/investor/policy.joblib`
- `data/investor_v3/summary.json`

Arena traders are **separate** genomes simulated on `pred_ret`; only the **Investor** tab is the real v3 allocator.

## Current health check (local)

Typical stale signals:

- `decisions.json` last day has **0 picks** (filters too tight or predictions end early)
- Backtest **total return negative** on test window (not proof forward edge fails, but not encouraging)
- `decisions` file older than latest predictor retrain — re-run investor after predictor refresh

## Reset & rebuild (recommended order)

```powershell
cd C:\Users\nicho\Nostradamus_remote_audit

# 1. Refresh predictor test outputs (investor reads this)
python scripts/train-investor-v3.py --help   # see flags
# Or full nightly pipeline:
# scripts/daily_market_close.ps1

# 2. Retrain investor (UI button or API)
# Investor tab → "Retrain now", or:
curl -X POST http://127.0.0.1:8000/api/retrain

# Or CLI directly:
python scripts/train-investor-v3.py `
  --top-k 5 `
  --min-proba 0.58 `
  --min-pred-ret 0.015 `
  --max-position-frac 0.15 `
  --kelly-scale 0.4
```

## Improve (honest levers)

| Lever | Effect |
|--------|--------|
| Lower `--min-proba` / `--min-pred-ret` | More picks; more turnover; more overfit risk |
| Lower `--top-k` | Concentrated book |
| Lower `--kelly-scale` / `--max-position-frac` | Smaller bets; smoother equity |
| Refresh `test.csv` after predictor champion change | Investor policy matches current signal |
| Congress / insider weights in train script | Already in feature set; tune env `CONGRESS_POLICY_WEIGHT` |

**Do not** weaken live-trading readiness gates to make backtest look better.

## Arena vs Investor UI

Arena trader drill-down now uses the **same book UI** as the Investor tab (day slider, pick cards, equity curve). Data is still **simulated arena pulses**, not `decisions.json`.
