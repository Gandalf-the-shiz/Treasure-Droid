# Megamind: concentration_risk (high)

## North star
Prepare the best **Robinhood AI agent** candidate: simulated trades on **real market data** (live ML panel + feeds), PnL from model `pred_ret` vs real symbols — not live fills until readiness permits.

## Objective
Megamind will update the best v3+ arm or spawn a new one (profit-focused) — v1/v2 frozen.


## Context
- **Finding:** Winners cluster in ['SDOT', 'JDZG', 'XOS'] (often warrants).
- **Arena v1** mean cumulative: 6.7851% · best trader #7
- **Arena v2** mean cumulative: 3.5688% · best trader #0
- **v2 beating v1:** False
- Arena P&L is **simulated** from `pred_ret` on `data/predictions_v3/live.csv` — not live fills.

## Repos
- Primary: `Nostradamus_remote_audit` (intelligence, arena, dashboard, `scripts/serve.py`)
- Email/UI bridge: `nostradamus-live` (`nostradamus_live/research/daily_report.py`, `nostra_ui_bridge.py`)

## Implementation steps
1. Read existing code paths for `concentration_risk` — search before editing.
2. Implement the smallest correct change that satisfies the finding; match local naming and patterns.
3. Wire into post-close flow if needed (`scripts/daily_market_close.ps1`, `megamind.py --tick`).
4. Verify: run relevant script or hit API; do not weaken `readiness` / live trading gates.

## Acceptance criteria
- [ ] Change addresses the finding with a measurable outcome (test, API field, or logged artifact).
- [ ] No secrets committed; paper/dryRun defaults preserved.
- [ ] Dashboard or daily email still loads if UI touched.

## Do NOT
- Open live trading or bypass the readiness gate to improve backtest metrics.
- **Delete, respawn, or modify Investor Arena v1 or v2** — only spawn new versions (v3+) or new data feeds.
- Respawn arena genomes unless explicitly requested (`regenerate_all.ps1 -RespawnArena` only).


## Investor Arena rules (Megamind — mandatory)

### v1 / v2 (frozen baselines)
- **Never** delete, respawn, or rewrite genomes.
- **Do** daily pulse (returns update; ledgers saved and snapshotted under `data/trader_arena/snapshots/`).

### Operating model (v3+)
- **Champion** (default v3): one evolving population (~112 traders). Cross-pool **harvest** from all ledgers (incl. archived forks); **evolve** replaces bottom quartile.
- **Challenger** (optional): at most **one** extra mutable arm when testing a **new feed/hypothesis**; old challenger archived when replaced.
- **Pulse** only `active` versions: v1, v2, champion, challenger (`--version active`). Archived pools (v4–v6) are harvest-only.
- **Prefer update** champion; **spawn** challenger only for new feeds — never duplicate pools for the same panel.
- **Real ML agents:** `data/intelligence/real_agents/registry.json` — 1 predictor + ≤4 policy slots from champion top sim.

- Do **not** run `--respawn` on v1/v2.


## When done
Update `data/intelligence/megamind/registry.json` recommendation `dbff372c7c0b` status to `implemented` if appropriate.
