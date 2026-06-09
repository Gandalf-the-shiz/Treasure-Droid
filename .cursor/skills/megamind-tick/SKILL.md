---
name: megamind-tick
description: >-
  Runs the Megamind post-close tick and verifies arena/registry state. Use when
  the user asks for megamind --tick, post-close intelligence refresh, or daily
  Megamind pulse after market close.
disable-model-invocation: true
---

# Megamind tick (post-close)

## Purpose

Run Megamind's meta-agent tick after market data is fresh. This produces/updates recommendations; it does **not** open live trading.

## Prerequisites

- Repo root: `Nostradamus_remote_audit`
- `PYTHONPATH=scripts`
- Live panel ideally refreshed first (`generate_live_predictions.py` or full `daily-market-close` skill)

## Checklist

1. Confirm arena active pulse already ran (or run it via **arena-pulse** skill first).
2. From repo root:

```powershell
$env:PYTHONPATH = "scripts"
python scripts/intelligence/megamind.py --tick
```

3. Verify artifacts updated:
   - `data/intelligence/megamind/latest_report.json`
   - `data/intelligence/megamind/registry.json`
4. If a task is approved and queued, check:
   - `data/intelligence/megamind/pending_for_agent.json`
   - `.cursor/rules/megamind-active-task.mdc`
5. Optional API checks (if `scripts/serve.py` is running):
   - `GET /api/arena/operating`
   - `GET /api/real-agents`

## Verification commands

```powershell
python -c "import json; p='data/intelligence/megamind/registry.json'; d=json.load(open(p)); print('recommendations', len(d.get('recommendations',{})))"
Get-ChildItem data/trader_arena/snapshots -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 Name, LastWriteTime
```

## Do NOT

- Weaken readiness or live-trading gates.
- `--respawn` arena v1/v2.
- Commit `config/megamind.secrets.json` or API keys.
