---
name: concentration-risk
description: >-
  Implements Megamind concentration_risk findings: measure symbol concentration
  in winner ledgers, expose via API or logged artifact, and add concentration
  caps in policy genomes. Use when implementing the active Megamind task or
  concentration risk in arena or real agents.
disable-model-invocation: true
---

# Concentration risk (Megamind)

## Purpose

Address winner clustering in a few symbols (often warrants). Produce a **measurable** outcome without weakening live-trading gates.

Active recommendation: `6948bd9c88a5` — winners cluster in `XXII`, `SDAWW`, `MPU`.

## Before editing

1. Read `.cursor/rules/megamind-active-task.mdc` and `data/intelligence/megamind/CURRENT_AGENT_PROMPT.md`.
2. Search existing paths:
   - `scripts/intelligence/ultimate_model.py` (recommendation area)
   - `scripts/intelligence/arena/mutable.py` (`concentration_risk` spawn spec)
   - `scripts/intelligence/arena/` ledgers and policy genomes
   - `scripts/serve.py` arena/real-agents API routes
3. Match local naming; smallest correct diff.

## Implementation checklist

1. **Measure** symbol concentration in top/winner ledgers (v3+ champion first):
   - Herfindahl or top-N share of PnL-weighted positions
   - Per-symbol counts in winning books over last N pulses
2. **Artifact** — at least one of:
   - New field on `GET /api/arena/operating` or leaderboard payload
   - Logged JSON under `data/intelligence/megamind/concentration_report.json`
   - Entry in `latest_report.json` metrics section
3. **Policy** — concentration caps in champion policy genomes (v3+ only):
   - Max weight per symbol / max warrant exposure
   - Liquidity or price filters aligned with `mutable.py` spawn spec
4. **Wire** post-close if needed: `scripts/daily_market_close.ps1` or `megamind.py --tick` path.
5. **Verify** dashboard and daily email still load if UI touched.

## Verification commands

```powershell
$env:PYTHONPATH = "scripts"
python scripts/intelligence/megamind.py --tick
python scripts/intelligence/trader_arena.py --pulse --version active --traders 100
# If serve running:
curl -s http://127.0.0.1:8000/api/arena/operating
```

## Acceptance criteria

- [ ] Measurable concentration metric (test, API field, or logged artifact)
- [ ] No secrets committed; paper/dryRun defaults preserved
- [ ] Dashboard/daily email loads if UI touched
- [ ] Registry `6948bd9c88a5` → `implemented` when done

## Do NOT

- Open live trading or bypass readiness to improve sim metrics.
- Modify, delete, or `--respawn` arena v1/v2.
- Spawn duplicate pools for the same panel — prefer champion update.
