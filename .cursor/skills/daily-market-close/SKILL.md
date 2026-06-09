---
name: daily-market-close
description: >-
  Orchestrates the full post-close pipeline via scripts/daily_market_close.ps1
  with verification steps. Use when the user asks for daily close, post-close
  update, or end-of-day Nostradamus refresh.
disable-model-invocation: true
---

# Daily market close

## Purpose

Run the full post-close intelligence refresh. **Does not respawn** arena genomes (preserves experiments).

## Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/daily_market_close.ps1
```

Or from repo root (script sets `$RepoRoot` internally).

## Pipeline order (reference)

1. Incremental `fetch-history.py` (timeout ~25 min)
2. Live ML panel, NPU status, congress/insider feeds
3. Mass psychology, insider monitor, execution feedback, forward IC
4. Champion sync → arena consolidate → **arena pulse active** → harvest-evolve
5. **Megamind `--tick`** → intelligence brain → trade manifests
6. Penny scan → learning harness (daily; weekly on Sunday)

## Verification checklist

After run completes:

1. **Log file** — newest under `logs/daily-close-update-*.log` ends with `[close] done`
2. **Live panel** — `data/predictions_v3/live.csv` mtime recent
3. **Arena** — pulse + snapshot under `data/trader_arena/snapshots/`
4. **Megamind** — `data/intelligence/megamind/latest_report.json` mtime recent
5. **No respawn** — grep log for `respawn`; should not appear for v1/v2

```powershell
Get-ChildItem logs/daily-close-update-*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content -Tail 15
Select-String -Path (Get-ChildItem logs/daily-close-update-*.log | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName -Pattern "respawn"
```

## Environment notes

- Python: `Python311-arm64` if present, else `python`
- Sets `PYTHONPATH`, `PREFER_NPU`, `UNIFIED_SCORE_ENABLED`, `ALLOW_SHORTS`
- `SEC_USER_AGENT` default if unset

## Do NOT

- Add `--respawn` to arena steps.
- Weaken readiness/live gates in any script touched.
- Commit secrets from `config/megamind.secrets.json`.

## Related skills

- **arena-pulse** — arena-only subset
- **megamind-tick** — Megamind-only subset
