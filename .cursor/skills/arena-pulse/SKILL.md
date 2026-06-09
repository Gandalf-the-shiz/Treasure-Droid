---
name: arena-pulse
description: >-
  Pulses Investor Arena v1, v2, champion, and challenger only (--version active).
  Use when the user asks to pulse the arena, update trader ledgers, or run daily
  arena returns without respawning genomes.
disable-model-invocation: true
---

# Arena pulse (active versions)

## Purpose

Update simulated returns for **active** arena arms: v1, v2, champion (v3), and optional challenger. Saves ledgers and dated snapshots under `data/trader_arena/snapshots/`.

## Command

From repo root:

```powershell
$env:PYTHONPATH = "scripts"
python scripts/intelligence/trader_arena.py --migrate --pulse --version active --traders 100
```

Optional harvest + evolve (champion only, post-pulse):

```powershell
python scripts/intelligence/trader_arena.py --harvest-evolve
```

## Checklist

1. **Never** pass `--respawn` with v1 or v2 — frozen baselines must not be rewritten.
2. Run `--migrate` once per session if legacy paths may exist.
3. Confirm stdout shows pulse summaries for active versions.
4. Confirm new snapshot under `data/trader_arena/snapshots/` (date-stamped).
5. For operating model state: `GET /api/arena/operating` or read `data/intelligence/arena/operating.json` if present.

## Verification

```powershell
python scripts/intelligence/trader_arena.py --pulse --version active --traders 100 2>&1 | Select-Object -Last 20
```

## Do NOT

- `--respawn` on v1/v2 (`is_frozen` should skip; still never pass it intentionally).
- Pulse archived forks (v4+) — harvest-only.
- Delete or rewrite genomes/ledgers for v1/v2.
- Treat sim P&L as proof of forward edge.

## Related

- Full post-close: **daily-market-close** skill
- Megamind after pulse: **megamind-tick** skill
