# Operation Mega Yacht — execution tracker

**Owner stakes:** Forward paper must turn green before live capital. Ungodly returns require capturable edge on tradeable names — not arena sim or 15k-trial backtests.

**Last updated:** 2026-06-05

---

## Current scoreboard (measured)

| Metric | Value | Gate target | Status |
|--------|-------|-------------|--------|
| Forward paper return | −3.24% | ≥ +1% | FAIL |
| Forward paper Sharpe | −1.88 | ≥ 0.5 | FAIL |
| Paper marks | 545 | ≥ 20 days | PASS duration |
| Live forward IC days | 1 (synced) | ≥ 20 @ ≥0.01 | FAIL (building) |
| Honest eval edge_proven | false | true | FAIL |
| Tradeable quintile spread | −0.00046 | > 0 | FAIL |
| Auto-search DSR prob | 0.0 (15,744 trials) | — | OVERFIT RISK |

---

## Phase 0 — Stop the bleeding (Days 1–7)

| ID | Task | Status | Notes |
|----|------|--------|-------|
| 0.1a | Fix `PRED_V3_LIVE` → `predictions_v3/live.csv` | done | `nostradamus-live/config.py` |
| 0.1b | Canonical `v3_live_ic.json` schema (`n_days`, `mean_ic`, `points`) | done | `forward_score.py` syncs to live repo |
| 0.1c | Readiness accepts legacy + canonical IC fields | done | `readiness.py` |
| 0.1d | Daily v3 accuracy → gate path | pending | Port `score-accuracy.py` to v3 |
| 0.2a | Email catch-up after long close | done | `autonomous_loop.ps1` |
| 0.2b | Register `NostradamusDailyEmail` task | blocked | Access denied — run `setup_autonomous.ps1` locally |
| 0.2c | Single dashboard port | pending | Task uses 4174; ad-hoc 8000 |
| 0.2d | Penny-ML / tunnel crash loop | open | Audit supervisor restarts every ~60s |
| 0.3a | `config/tradeable_universe.json` | done | Single universe definition |
| 0.3b | `tradeable_universe.py` filter module | done | Shared tradability |
| 0.3c | Arena panel filter | done | `arena/engine.py` |
| 0.3d | Daytrade manifest filter | done | `daytrader_engine.py` |
| 0.3e | Swing manifest filter | done | `generate_trade_signals.py` |
| 0.3f | Freeze search churn cap | pending | Env `MEGA_YACHT_MAX_TRIALS_WEEK` |

**Phase 0 exit:** Gate reads live IC ≥1 day; warrants absent from manifests 10 days.

---

## Phase 1 — Truth layer (Weeks 2–4)

| ID | Task | Status |
|----|------|--------|
| 1.1 | Forward-gated promotion (`forward_gate.py`) | done |
| 1.2 | Dual paper sleeves (investor vs arena-tradable) | pending |
| 1.3 | Command Center Forward Truth panel | done |
| 1.4 | Promotion requires honest_eval edge_proven | pending |

## Phase A — Cross-sectional alpha engine (Alpha Doctrine) — **KEYSTONE DONE**

| ID | Task | Status | Result |
|----|------|--------|--------|
| A.1 | `scripts/intelligence/alpha/neutralize.py` | done | winsor + sector/size demean + rank/z |
| A.2 | `alpha/engine.py` market-neutral book | done | 419 tradeable, 41L/41S, net 0.0 |
| A.3 | `alpha/measure.py` IC/ICIR/spread proof | done | **spread flipped POSITIVE** |
| A.4 | Wire into harness + daily close | done | intraday+full+post-close |
| A.5 | Dashboard forwardTruth alpha metrics | done | blended spread + ICIR bars |

**Validated on test window (tradeable universe):**

| Signal | Mean IC | Quintile spread | ICIR |
|--------|---------|-----------------|------|
| Raw ML edge | 0.0267 | **−0.00052** (untradeable) | — |
| Neutralized ML edge | 0.0227 | −0.00018 | — |
| **Blended neutralized (ML+rev+mom)** | **0.0284** | **+0.00028** (tradeable) | **0.271** |

Blending uncorrelated sleeves + neutralization raised IC above the raw signal AND flipped the spread positive. Transfer Coefficient problem solved in backtest. See `docs/ALPHA_DOCTRINE.md`.

---

## Phase 2 — Capturable edge (Weeks 5–10)

| ID | Task | Status |
|----|------|--------|
| 2.1 | Cost-native training objective | pending |
| 2.2 | Arena capacity-adjusted sim PnL | pending |
| 2.3 | Investor v3 regime + dynamic Kelly | pending |
| 2.4 | Megamind concentration_risk → implemented | pending |

---

## Phase 3 — Information moat (Weeks 11–20)

| ID | Task | Status |
|----|------|--------|
| 3.1 | Survivorship-bias-free history | pending |
| 3.2 | Earnings surprise pipeline (Finnhub PEAD) | **done** |
| 3.2b | Analyst revisions sleeve (Finnhub) | **done** |
| 3.3 | Search cap 200 trials/month + shadow sleeves | pending |
| 3.4 | Real crowd or feature-off | pending |
| 3.5 | ICIR-weighted sleeve combination + auto-decay | **done** |

### Finnhub feed (live 2026-06-05)
- `config/secrets.json` (gitignored) + `scripts/app_secrets.py` loader — key never committed.
- `scripts/fetch_finnhub.py` — earnings surprise (SUE) + analyst recommendation trends; cached, rate-limited (60/min), incremental (refresh 5d, 200/run). Wired into daily close + full harness.
- `alpha/engine.py` blends **6 sleeves**: ml_edge, reversal_5d, reversal_1d, momentum_120_20, **pead**, **revisions**.

### Alpaca paper executor — **LIVE on paper 2026-06-05**
- `scripts/intelligence/alpha/alpaca_executor.py` — book → Alpaca **paper** orders. Whole-share qty (Alpaca rejects fractional shorts), asset-eligibility + borrow filter, per-side renormalization to stay dollar-neutral. Paper-only, safe-by-default.
- Keys in `config/secrets.json` (gitignored). Account: $100k equity, 4× buying power, shorting enabled.
- **First paper book placed:** 67 orders, 0 failures, 40L/27S, grossL $48.9k / grossS $49.4k, **net −$426 (dollar-neutral)**.
- Wired into `daily_market_close.ps1` → daily paper rebalance = forward scoreboard.

## Theoretical north star
- `docs/UNGODLY.md` — the full theoretical path to legendary returns: the expanded master equation (IC × √Breadth × TC × Leverage × Compounding − Costs − Decay), the alpha factory moat, the capital ladder, 12-month plan.

---

## Phase 4 — Capital ladder (Months 6–12)

| Stage | Capital | Condition |
|-------|---------|-----------|
| L0 | $0 live | **NOW** |
| L1 | $5k | 90d paper Sharpe ≥0.5 + edge_proven + 20d IC |
| L2 | $25k | L1 + 60d live Sharpe ≥0.3 |
| L3 | $100k | Capacity holds at size |
| L4 | $1M+ | Separate execution stack |

---

## Kill switches

- Forward 30d Sharpe < −0.5 → halve sizes, pause trials
- Warrant in manifest → P0 halt
- DSR < 0.5 on new champion → no promote
- Search > 200 trials/month → auto-pause

---

## Session log

| Date | Work |
|------|------|
| 2026-06-05 | Created tracker; Phase 0.1 IC path fix; tradeable universe + filters; forward_gate skeleton; Command Center forwardTruth + home UI; forward_score sync (1d IC=0.144 tradeable) |
| 2026-06-05 | **Alpha Doctrine** (`docs/ALPHA_DOCTRINE.md`) — researched Wall St + free APIs + Fundamental Law. Built cross-sectional alpha engine: neutralize/engine/measure. **Proved blended neutralized alpha flips quintile spread POSITIVE (+0.00028), IC 0.0284, ICIR 0.27.** Wired into harness + daily close + dashboard. |
| 2026-06-05 | **Finnhub live**: secrets loader (gitignored), `fetch_finnhub.py` (PEAD/SUE + analyst revisions, cached/rate-limited), 2 new sleeves in engine (now 6 total). **Alpaca paper executor** scaffold (safe dry-run, 82 orders). `docs/SOUND_SMART.md` glossary. |
| 2026-06-05 | **Alpaca paper LIVE** ($100k, shorting on); whole-share/borrow-filtered dollar-neutral book placed (64 orders, net ≈0), wired into daily close. `docs/UNGODLY.md` theoretical plan. |
| 2026-06-05 | **Front-end rebuild**: home page → "single pane of glass" KPI command center with plain-English explanations (forward vs research tags), market-neutral book panel, live Alpaca paper equity/P&L. New `/api/alpaca/account`, `alphaBook` in command-center. `docs/HOSTING.md` (keep compute local; Cloudflare Tunnel + domain vs Entra App Proxy; drop GitHub Pages). |
| 2026-06-05 | **REBRAND → Treasure Droid** (domain `treasure-droid.com`). Deep-space Star-Wars-salvage theme: `css/treasure-droid.css` (Bounty palette gold+navy+emerald, Orbitron/Rajdhani), generated rusty-droid mascot + app icon (`assets/`), hero banner, new copy (Cargo Holds, Droid's Crew, Bounties), brand API + manifest + favicon. Tagline "Mining the markets for buried treasure." |
| 2026-06-05 | **DEPLOYED LIVE → https://treasure-droid.com** via Cloudflare named tunnel → port 4174. Read-only-public guard (POST blocked from internet via CF headers; local unrestricted). DNS root+www, auto-HTTPS. Verified GET 200 / POST 403. Persistence via supervisor + default config. |
| 2026-06-06 | **UNIFIED ARCHITECTURE review** (`docs/UNIFIED_ARCHITECTURE.md`): fleet-of-sleeves + Treasure Droid captain. **Built The Crew** (`scripts/intelligence/fleet/`): 5 ML agents walking forward on paper, each with portfolio + trade history + ML-traced reasoning. Shared `build_alpha_frame()`. `/api/fleet` + wired into daily close/harness. |
| 2026-06-06 | **Megamind \u2192 Treasure Droid (captain)**: forward/fleet-aware recommendations (consumer-sentiment pipeline, re-weighted Treasure Arena vX, adjust genomes, promote models) — surfaced in **daily email** ("Treasure Droid recommends") + UI Captain page. Fixed run_tick stale-merge bug. **Starfield deep-space background** (`assets/starfield.png`) + rusted-robot palette. Tabs: Bridge / Captain. Verified: agent=Treasure Droid, 9 recs, email renders, starfield serves. |
| 2026-06-06 | **Deep analysis + handoff**: wrote `docs/HANDOFF.md` (master read-first: state, architecture mermaid maps, scoreboards, subsystem reference, file index, autonomous cadence, known gaps, next-task). Rebranded `README.md` to Treasure Droid + HANDOFF pointer (legacy V2 marked historical). Verified all data fresh + supervisors running + readiness correctly blocked. Next: per-sleeve forward IC. |
| 2026-06-06 | **600-genome search + sentiment gossip**: widened walk-forward (12 families, wider ranges) — 457 scored, **63/68 top genomes held up** on unseen holdout (best 3.08 Sharpe / 45.6%; sel→hold gap 5.4→1.1 shows overfit honestly). 4 survivors promoted (stable params-hash ids; dedup bug fixed; fleet=9). **Sentiment pipeline** `fetch_sentiment_feed.py`: Finnhub company-news→VADER + Reddit/crowd → per-symbol score → **sentiment alpha sleeve** (engine now 7 sleeves) + dated history snapshots for ML comparison. Wired into daily close + harness. (Finnhub social-sentiment is premium/403; news+reddit used. Google Trends optional/not installed.) |
| 2026-06-06 | **UX consolidation + speed + walk-forward**: tabs 11\u2192**5** (Bridge/Fleet/Markets/Captain/Chat; rest via Bridge "Cargo Holds" grid). QA: all 20 GET endpoints 200. **Images 4.8MB\u21920.6MB** (icon 1796\u219270KB, 280KB banner replaces 3MB mascot). Megamind recs reset + fresh tick. **Historical walk-forward** (`fleet/backtest.py`): spawn 200 genomes, SELECT on first 60% of OOS year, JUDGE on held-out tail, returns clipped \u00b115%/day. Honest caveat baked in (correlated genomes / predictor's own test set = upper bound). Top survivors promoted into live Fleet (8 agents now) to prove forward. `/api/walkforward` + Captain UI + weekly harness. |
| 2026-06-06 | **Fleet Cockpit UI** (`js/rh-pages/fleet.js`, route `#/fleet` + `#/fleet/{id}`, tab 🏴‍☠️ Fleet): crew overview (equity/forward return/positions per agent, leader 👑) → agent drilldown (KPIs + equity curve + portfolio with tap-to-expand ML reasoning per pick + trade history). Educational copy throughout. Auto-coder set to reliable IDE one-click (cloud wired, off by default). |
| 2026-06-06 | **Auto-coder fixed**: root cause = cursor-sdk LOCAL runtime broken on Win ARM64 (WinError 10038) + no cursor-agent CLI. Guarded local SDK off (no more crashes/spam); approvals now reliable IDE handoff (prompt + active rule, non-disruptive `autoLaunch=none`). Rewrote `megamind_run_agent.py` as robust **cloud** auto-coder (opens PR via GitHub remote, no local sockets) behind `autoBuildMode=cloud`. Removed double-spawn in auto_approve. **Autonomy options pending user choice:** cloud PRs (needs repo synced to GitHub) vs install cursor-agent CLI. |
| 2026-06-06 | **Per-sleeve forward IC + ICIR weights** (`alpha/sleeve_ic.py`): daily neutralized snapshots, test-window research IC per sleeve (ml_edge 0.023, reversal_1d 0.020, momentum 0.016), forward accrual from snapshots, ICIR-weighted blend + auto-decay when trailing IC &lt; 0. Engine reads live weights; Bridge shows sleeve scoreboard table. Wired daily close + harness. Captain recs sleeve decay. |
| 2026-06-06 | **MAD SCIENTIST LAB** (`historical/panel_builder.py` + `walkforward_lab.py`): historical panel 2.25M rows / 502 days / 4648 symbols matching live outputs (preds + PIT sleeves + alpha frame). 500-genome day-by-day walk-forward on 2024–2025; survivors promoted to shadow fleet. Mantra rebrand. Breadth 2500. `docs/MAD_SCIENTIST.md`. Bridge lab panel. |

---

## Next up (always pick from top)

1. **Breadth (Phase B):** raise live universe past 800 → 3,000+ (more √breadth). `LIVE_PREDICT_LIMIT` + full ticker list.
2. **PEAD + revisions sleeves (Phase C):** wire Finnhub free tier → earnings surprise (SUE) + analyst revision breadth. Highest-ROI new alpha (20–60d, 4–8% drift). Needs `FINNHUB_API_KEY`.
3. **Multi-horizon labels (Phase B):** predictor exports 5d + 20d targets so longer-horizon sleeves can be measured/blended.
4. **Forward paper sleeve** for the alpha book in `nostradamus-live` (market-neutral L/S) → prove forward, not just backtest.
5. ~~**ICIR-weighted sleeve combination** + auto-decay~~ **done** — accrues forward per-sleeve IC daily; auto-weights after 5 days.
6. **Daily v3 accuracy** scorer → gate path (replace stale v2 log).
7. Register `NostradamusDailyEmail` task (run `setup_autonomous.ps1` elevated).
8. Mark Megamind `concentration_risk` implemented after 10 warrant-free manifest days.

### Decisions / waiting on you
- **Finnhub API key** (free at finnhub.io) unlocks PEAD + revisions — the two most robust documented anomalies. Drop it in `config/` or env `FINNHUB_API_KEY` and I'll build those sleeves.
- **Alpaca keys** (free) unlock a real market-neutral paper/live execution path parallel to Robinhood.
