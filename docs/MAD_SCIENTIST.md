# Mad Scientist Doctrine

**Mantra:** Experiment relentlessly on history. Prove forward on paper. Unleash capital only when the data screams yes.

Honesty still matters — we label upper bounds vs forward truth. But the *energy* is mad-scientist: spawn, test, kill, promote.

---

## The experiment loop

```
8yr OHLCV train (≤2023)  →  predictor v3 model
         ↓
Historical panel (2024–2025)  →  same columns as live Treasure Droid
  (pred_proba_up, pred_ret, edge, n_<sleeve>, alpha, y_ret, price)
         ↓
Mad Scientist Lab  →  500 genomes × day-by-day walk-forward
         ↓
Select 60% / judge 40%  →  promote survivors to shadow fleet
         ↓
Forward paper (live)  →  only real proof → capital ladder
```

---

## Key scripts

| Script | What it does |
|--------|----------------|
| `scripts/intelligence/historical/panel_builder.py` | Builds `data/intelligence/historical/panel.parquet` from val+test + PIT sleeves + alpha frame |
| `scripts/intelligence/historical/walkforward_lab.py` | Spawns genomes, walks day-by-day, promotes winners |
| `config/mad_scientist_lab.json` | Train/walkforward dates, genome count, promote count |

---

## Panel must match live machine

Live outputs per symbol per day:

- `date`, `symbol`, `sector`, `pred_proba_up`, `pred_ret`
- `edge`, `alpha`, `price`
- `n_ml_edge`, `n_reversal_1d`, `n_reversal_5d`, `n_momentum_120_20`, …
- `y_ret` (realized next-day return for scoring)

Sparse live sleeves (PEAD, revisions, sentiment) need **dated feed backfill** before they appear in historical panel. Price + ML sleeves work today.

---

## Next experiments (always scheming)

1. Backfill dated Finnhub + sentiment snapshots → full 7-sleeve historical panel
2. Rolling retrain: retrain predictor every 6 months on trailing 8yr, rescore walkforward chunk
3. Multi-horizon labels (5d, 20d) → longer-horizon sleeves in panel
4. Breadth: full 3,000+ tradeable universe in panel (not subsampled)
5. Per-sleeve genome families tied to `sleeve_ic.json` forward IC

---

## Run it

```powershell
# Build panel + run lab (weekly harness does this automatically)
python scripts/intelligence/historical/panel_builder.py
python scripts/intelligence/historical/walkforward_lab.py --genomes 500 --promote 5

# Rebuild live panel at higher breadth
$env:LIVE_PREDICT_LIMIT="2500"
python scripts/generate_live_predictions.py
```
