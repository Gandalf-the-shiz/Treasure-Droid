# Treasure Droid Reasoning — deep dive

**Short answer:** Treasure Droid is **three agents**, not one. Only **Chat** and the **Reasoning Agent** use a real LLM today. The **Captain** is a rules engine with optional Gemini narrative — and that's intentional for money decisions.

---

## The three brains

| Agent | File | Type | Smart for what? |
|-------|------|------|-----------------|
| **Captain (Treasure Droid)** | `megamind.py` + `ultimate_model.py` | Rule-based meta-agent + optional LLM narrative | Governance, promotion gates, experiment queue — **zero hallucination** |
| **Reasoning Agent** | `reasoning_agent.py` | **LLM** (Gemini 2.5 Flash when keyed) | Strategy narrative overlay on top ML picks |
| **Chat / Oracle** | `serve.py` `/api/chat` + `npu_llm.py` | **LLM** (Gemini → Phi-3 NPU → template) | Q&A about your system's numbers |
| **Fleet explainability** | `fleet/reasoning.py` | Deterministic math trace | Per-pick audit trail (not LLM) |
| **Mad Scientist Lab** | `historical/walkforward_lab.py` | Evolutionary search (not LLM) | Breed traders on 2yr historical panel |

---

## Is the Captain a "reasoning agent"?

**Not in the AGI sense.** It does not chain-of-thought over open-ended problems.

What it **does** (and does well):

1. Reads structured JSON: forward IC, fleet P&L, lab results, arena stats, readiness gates
2. Applies **fixed policies**: if sleeve decayed → zero weight; if forward IC < 20d → don't promote
3. Emits **recommendations** you approve → IDE handoff builds the next experiment
4. Optionally calls `generate_text()` (Gemini) for a **human-readable narrative** — not for trading decisions

This is how production quant shops work: **models decide numbers; policies decide capital.**

---

## Is the Reasoning Agent a real reasoning agent?

**Yes — it's an LLM strategist layer.**

Each tick (`reasoning_agent.py --tick`, every 15 min via `continual_reasoning.ps1`):

1. Loads top ML picks from `live.csv`
2. Loads regime/macro context
3. Prompts the LLM: *"You are a paper-trading equity strategist…"*
4. Writes narrative + paper portfolio state

**Your machine today:** `llm_status.json` shows **`backend: gemini`**, model **`gemini-2.5-flash`**. That is a real, capable reasoning model — fast, cheap, good at structured context.

**Fallback chain** (`npu_llm.py`):

```
Gemini API (GOOGLE_API_KEY)  →  Phi-3 on NPU (onnxruntime-genai)  →  template (keyword router)
```

---

## Do you need a beefier model?

| Use case | Recommendation |
|----------|----------------|
| **Chat / explain the dashboard** | Gemini 2.5 Flash is **enough** — grounded in JSON context |
| **Captain daily narrative** | Flash is enough; optional Pro for longer synthesis |
| **Reasoning Agent strategy** | Flash is fine; upgrade if you want multi-step macro reasoning |
| **Autonomous trading decisions** | **Do NOT use LLM** — use ML + rules + forward gates (current design) |
| **Code/build from approvals** | Cursor Agent (IDE) — separate from trading brain |

**You do NOT need GPT-4-class models for this app to work.** The edge is in **IC × breadth**, not eloquence.

### Local vs API

| Backend | Your hardware | Verdict |
|---------|---------------|---------|
| **Gemini API** | Any | ✅ **Best today** — already working, ~$0 for Flash tier |
| **Phi-3 + NPU (QNN)** | Snapdragon X, 3 QNN devices detected | 🟡 Good for offline chat; install `onnxruntime-genai` + Phi-3 weights |
| **Template fallback** | Always | 🔴 Keyword router — not reasoning, emergency only |

**Local NPU is NOT too shitty** for chat/narrative. It is **too weak** to replace your ML stack (predictor v3, alpha engine) — those use gradient boosting + rules, not LLMs.

**API call Gemini for reasoning; keep ML local.** That's the optimal split on your box.

---

## How Mad Scientist feeds Captain → new ML traders

```
Historical panel (matches live outputs)
        ↓
mad_scientist_loop.py (every 3h, 24/7)
  → rotate experiment profiles
  → 300–600 genomes × day-by-day walk-forward
  → log to experiment_log.jsonl
  → promote survivors → fleet registry (shadow MS-* agents)
        ↓
Fleet forward paper (real prices, fake money)
        ↓
Captain reads: lab champions + forward P&L
        ↓
Promote shadow → live paper allocation (when forward Sharpe clears gate)
        ↓
Live capital (readiness gate — still blocked until proven)
```

**Integration points (live in code):**

- `walkforward_lab.py` → `_promote_survivors()` → `fleet/registry.py`
- `mad_scientist_loop.py` → `experiment_log.jsonl` + `loop_state.json`
- `ultimate_model.py` → `mad_scientist_lab` recommendation
- `fleet/run.py` → steps all agents including MS-* shadows daily

---

## How to improve historical data (the key)

Current panel has ML + price sleeves. Missing for full live parity:

| Gap | Fix | Priority |
|-----|-----|----------|
| Dated PEAD/revisions | Backfill Finnhub snapshots per date | High |
| Dated sentiment | Extend `fetch_sentiment_feed.py` history | High |
| Multi-horizon labels | Train 5d/20d targets in predictor v3 | Medium |
| Full 3k+ breadth | Raise `LIVE_PREDICT_LIMIT`, rescore panel | Medium |
| Rolling 8yr retrain | Retrain every 6mo on trailing window | Medium |
| Regime/congress PIT gaps | Backfill overlay snapshots | Low |

**The simple answer you gave is correct:** historical dataset must match live Treasure Droid outputs column-for-column. We're 80% there; sparse sleeves need dated backfill.

---

## 24/7 operation

| Loop | Cadence | What it does |
|------|---------|--------------|
| `continual_mad_scientist.ps1` | **Every 3 hours** | Genome experiments on historical panel |
| `continual_improve.ps1` | Every 6h | Arena evolve + Captain tick |
| `continual_trader_arena.ps1` | Every 1h | Arena pulse |
| `continual_reasoning.ps1` | Every 15m | LLM reasoning agent |
| `daily_market_close.ps1` | Post-close | Full pipeline + lab |
| `penny_ml_search.ps1` | Endless | Penny ML trials |

**Restart supervisor to pick up mad-scientist child:**

```powershell
# If autonomous_loop task is running, restart it — or start manually:
powershell -File scripts\continual_mad_scientist.ps1 -SleepMinutes 180
```

Pause all loops: create `data/PAUSED.txt`.
