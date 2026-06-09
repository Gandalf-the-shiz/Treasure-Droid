# The Alpha Doctrine — how Nostradamus buys the mega yacht

**This is the strategy bible. Every build decision serves the equation below.**

Last updated: 2026-06-05

---

## 1. The one equation that buys yachts

Richard Grinold's Fundamental Law of Active Management — the single most important idea in quant investing:

```
Information Ratio  =  IC  ×  √Breadth  ×  Transfer Coefficient
        IR         =  skill ×  √(# independent bets) × (how much skill you actually deploy)
```

**The casino proof (Morgan Stanley / Grinold-Kahn):** A roulette wheel gives the house an edge (IC) of just **2.7%**. On **one** bet, the house's information ratio is 0.027 — basically noise. On **1,000,000** bets, the IC is unchanged but the IR explodes to **27.0** because √1,000,000 = 1,000.

> **The house is not smarter than you. It just bets more often with a tiny, relentless edge.**

This is the secret hiding in plain sight. Renaissance's Medallion (~66%/yr for 30 years) is **not** built on being right 90% of the time. Their per-trade hit rate is reportedly barely above 50%. They win because they place **millions of small, independent, market-neutral bets** with a tiny edge, repeated relentlessly.

### What this means for us

| Lever | What it is | Our current state | The move |
|-------|-----------|-------------------|----------|
| **IC** (skill) | Correlation of forecast vs outcome | ~0.025 tradeable rank IC — **this is already real and valuable** | Raise via better/more signals; stabilize (ICIR) |
| **Breadth** | # of independent bets/year | ~800 names, 1 horizon, 1 signal, 1×/day | **Explode it**: full universe × multiple horizons × many uncorrelated sleeves |
| **TC** (transfer) | How much signal survives constraints/costs | Low — long-only, microcap-polluted, negative tradeable spread | Market-neutral L/S, neutralize sector/size, cost-aware |

**"Improve the rate of accuracy"** = raise **ICIR** (mean IC ÷ std IC) and **breadth**. A 0.025 IC that shows up *every day across thousands of names* beats a 0.10 IC that shows up once a month. Consistency × volume is the whole game.

---

## 2. Brutal diagnosis (where we are vs the law)

From the honest eval + forward paper:

- **IC is real but tiny and long-only-untradeable.** Raw IC 0.072, tradeable 0.025, but **quintile spread is negative** on tradeable names → the edge lives in microcaps/warrants we can't trade at size. *We are violating the Transfer Coefficient.*
- **Breadth is tiny.** 1-day horizon, ~800 names, one model. √breadth is small → IR capped low even if IC were great. *We are starving the √Breadth term.*
- **One signal.** Predictor v3 is a single price/technical model + thin overlays. No earnings drift, no revisions, no options, no real sentiment. *We have one bet type when the law rewards many uncorrelated ones.*
- **Absolute, not relative.** We predict "up tomorrow" (drowns in market beta) instead of "outperforms peers" (pure alpha). *Legends predict cross-sectional relative returns.*

**Verdict:** The model isn't dumb. The **architecture around it** is leaving the yacht on the table.

---

## 3. How the legends actually operate (distilled)

| Firm | The secret (decoded) | What we steal |
|------|----------------------|---------------|
| **Renaissance (Medallion)** | Millions of tiny, short-horizon, market-neutral bets; signal processing on patterns; ruthless cost/slippage modeling; ~50.x% hit rate that compounds | Breadth obsession; market-neutral; trade the edge relentlessly, not rarely |
| **Two Sigma** | Industrialized scientific method; **ensembles** of many models; massive alternative data; real-time feature reweighting by regime | Ensemble many weak sleeves; reweight by recent IC; alt-data pipeline |
| **Citadel** | Multi-strategy; dynamically allocate capital to whatever's working; world-class execution + real-time risk | Capital allocation across sleeves by live Sharpe; execution feedback loop |
| **WorldQuant** | "Alpha factory" — thousands of weak alphas (each IC ~0.01–0.03) combined; if each is independent, the combination is gold | **The core model**: many cheap alphas, combined, beats one expensive alpha |
| **DE Shaw / PDT** | Stat-arb on relative mispricings; portfolio optimization with risk model | Cross-sectional ranking + neutralization + risk-aware sizing |

**The universal pattern:** *acquire data → engineer many weak signals → combine → neutralize → size by conviction & risk → execute cheaply → measure forward → kill decayed alphas, add new ones faster than they decay.*

Alpha decays. The moat is **research velocity**, not any single signal. Our autonomous loop + arena is *exactly* the right shape for this — it just needs to be pointed at the right target (cross-sectional, neutral, multi-sleeve, breadth-maxed).

---

## 4. The Doctrine — 7 pillars

1. **Predict relative, not absolute.** Cross-sectional rank of expected residual return (vs sector/size peers), not "up/down tomorrow."
2. **Market-neutral by construction.** Long top decile, short bottom decile, beta ≈ 0. Removes market risk, isolates skill, doubles breadth (longs *and* shorts are bets).
3. **Many weak alphas > one strong model.** Each sleeve only needs IC ~0.01–0.03. Combine 5–10 *uncorrelated* sleeves. This is the WorldQuant alpha-factory.
4. **Maximize breadth.** Full liquid universe (3,000+ names) × multiple horizons (1d, 5d, 20d) × daily. Breadth is free IR.
5. **Neutralize relentlessly.** Winsorize → sector-demean → size-demean → rank/z-score every sleeve before combining. This *fixes the negative tradeable spread.*
6. **Cost & capacity are first-class.** Optimize net-of-cost spread; cap position by ADV; nothing that dies after 10 bps slippage ships.
7. **Forward truth or it didn't happen.** ICIR + forward paper on tradeable universe is the only scoreboard. Promote on forward, not backtest. Kill decayed sleeves automatically.

---

## 5. The free-data arsenal (zero/low cost)

Each new independent feed = more breadth + a new uncorrelated sleeve.

| Source | Free? | Data | Sleeve it powers |
|--------|-------|------|------------------|
| **yfinance / Stooq bulk** | Free | OHLCV (have it) | Momentum, reversal, vol, size |
| **SEC EDGAR** | Free (UA) | 10-K/Q/8-K, Form 4 insider, 13F | Insider cluster, institutional flow |
| **FRED** | Free | 800k macro series | Regime gating |
| **Finnhub** | Free tier | 30yr fundamentals, **earnings surprise**, **analyst estimates/revisions**, insider, some congress | **PEAD**, **revisions** (the two most robust anomalies) |
| **Financial Modeling Prep** | Free tier | Statements, earnings calendar, **transcripts**, 13F, insider | PEAD, quality/value, transcript NLP |
| **Quiver Quant** | Free (delayed) | Congress, gov contracts, patents, WSB sentiment | Congress, retail-attention, gov-spend |
| **SecuritiesDB** | Free, no key | Piotroski/Altman/Beneish, Fama-French factors, **passive ETF float**, insider flow | Quality, factor-neutralization, crowding |
| **ORTEX** | Free tier | **Short interest**, cost-to-borrow, days-to-cover, put/call, EPS momentum | Short-squeeze, options sentiment |
| **GDELT** | Free | News tone/volume (have it) | News-shock sentiment |
| **Alpaca** | Free | Paper + live commission-free execution, market data | **Execution path** (Robinhood alternative/parallel) |
| **QuantConnect LEAN** | Free | Backtest engine, 15yr tick data | Research velocity |

**Priority order to wire:** Finnhub (PEAD + revisions) → SecuritiesDB (factors + passive float, no key) → ORTEX (short interest) → FMP (transcripts NLP) → Alpaca (execution).

---

## 6. Alpha sleeves (the factory)

Documented anomalies, each a sleeve. Target IC per sleeve only needs to be 0.01–0.03; the magic is in combining uncorrelated ones.

| Sleeve | Signal | Documented edge | Horizon | Status |
|--------|--------|-----------------|---------|--------|
| **ML edge** | Predictor v3 cross-sectional, neutralized | ~0.025 IC tradeable | 1d | have model, needs neutralization |
| **PEAD** | Earnings surprise (SUE) drift | +4–8% top-quintile 60d drift; "most replicated anomaly" | 20–60d | **build** (Finnhub) |
| **Analyst revisions** | Up/down revision breadth | 4–6% L/S spread, 3–6mo | 20–60d | **build** (Finnhub) |
| **Momentum (residual)** | 6–12mo return, sector-neutral | Classic, persistent | 20–120d | build (have OHLCV) |
| **Short-horizon reversal** | 1–5d overreaction reversal | Strong in liquid names | 1–5d | build (have OHLCV) |
| **Insider cluster** | Form 4 CEO/CFO cluster buys | Real, in overlays today | 20–60d | have, neutralize |
| **Congress** | Disclosed trades | Weak/noisy — gate on forward IC | 20–60d | have, prove or cut |
| **Short squeeze** | High SI + cost-to-borrow + momentum | Episodic, high vol | 5–20d | build (ORTEX) |
| **Quality/value** | Piotroski/Altman + cheapness | Slow, diversifying | 60–250d | build (SecuritiesDB) |
| **News/retail attention** | GDELT + WSB spikes | Short, behavioral | 1–10d | partial (GDELT, mass_psych) |

**Combination:** neutralize each → weight by trailing ICIR (Two Sigma style) → sum → re-rank → market-neutral book. Sleeves with decayed/negative forward IC get auto-zeroed.

---

## 7. Build roadmap (mapped to the law)

### Phase A — Transfer Coefficient (fix what we have) ← **NOW**
- [x] Tradeable universe everywhere (done — Mega Yacht 0.3)
- [ ] **Cross-sectional alpha engine**: neutralize (sector/size) + rank predictor edge → market-neutral L/S book
- [ ] **Cross-sectional IC measurement** (ICIR, quintile spread, breadth) on tradeable universe → gate path
- [ ] Confirm neutralized quintile spread turns **positive** (the whole point)

### Phase B — Breadth (free IR)
- [ ] Score **full liquid universe** (3,000+), drop the 800 cap
- [ ] Multi-horizon labels (1d, 5d, 20d) in predictor retrain
- [ ] Long/short doubles bet count

### Phase C — The alpha factory (more uncorrelated IC)
- [ ] Finnhub feed → **PEAD** + **revisions** sleeves (highest-ROI new alpha)
- [ ] Residual momentum + short-term reversal sleeves (from OHLCV we own)
- [ ] ICIR-weighted sleeve combination + auto-decay
- [ ] SecuritiesDB factors → proper risk-model neutralization

### Phase D — Execution & capital ladder
- [ ] Net-of-cost optimization + ADV capacity caps
- [ ] Alpaca paper parity → execution feedback → live ladder (gated)
- [ ] Capital allocation across sleeves by live Sharpe (Citadel style)

---

## 8. Targets (honest, ambitious)

The law tells us what's reachable. With **0.03 blended IC** across **~5 uncorrelated sleeves** over **~2,000 names daily** market-neutral, a top-quartile IR (0.8–1.5) is the realistic prize. That maps to roughly:

| Blended IC | Sleeves (indep) | Universe | Plausible net Sharpe | Net CAGR band |
|-----------|------------------|----------|----------------------|---------------|
| 0.02 | 2 | 800 | 0.3–0.6 | single digits |
| 0.03 | 4 | 2,000 | 0.8–1.2 | 15–30% |
| 0.04 | 6 | 3,000 | 1.2–2.0 | 30–60% |

**Yacht math:** sustained **25–40% net** compounds a serious book into yacht territory over years; the stretch (>40%) needs the full factory humming *and* it to survive forward paper. We do not assume it — we **earn it forward**, then size via the capital ladder.

---

## 9. What's being built right now

`scripts/intelligence/alpha/` — the cross-sectional alpha engine:
- `neutralize.py` — winsorize, sector/size demean, rank & z-score (pure, tested)
- `engine.py` — predictions → neutralized blended alpha → market-neutral L/S book
- `measure.py` — cross-sectional ICIR + quintile spread + breadth → gate path

This is Phase A: stop violating the Transfer Coefficient. Turn the real-but-trapped 0.025 IC into a tradeable, market-neutral, breadth-scaled book — the foundation the whole factory bolts onto.

> Skill × Opportunity. We have skill. This builds the opportunity to express it.
