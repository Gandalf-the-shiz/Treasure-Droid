# Autonomous Learning Harness

Continuous local ML loop optimized for **zero cloud cost** and **Snapdragon NPU**
inference (FinBERT sentiment via ONNX QNN).

## Quick start

```powershell
# Single full cycle
python scripts/learning_harness.py --once

# Market-aware continuous brain (recommended)
powershell -File scripts/continuous_brain.ps1

# Fixed 24h harness loop (legacy)
powershell -File scripts/autonomous_loop.ps1

# Custom interval
$env:LEARNING_LOOP_HOURS = "12"
powershell -File scripts/autonomous_loop.ps1
```

## What each cycle does

1. **NPU probe** — `npu_runtime.py` → `data/learning/npu_status.json`
2. **Data canals** — feeds, macro, regime, congress, insider, history
3. **Train predictor v3** — OHLCV + regime + congress + insider overlays
4. **Promotion gate** — challenger vs champion (`promotion_gate_v3.py`)
5. **Train investor** — policy + backtest + `decisions.json`
6. **Enrich** — FinBERT on NPU (sentiment) + congress tags on picks
7. **Signals** — `data/trading/robinhood_manifest.json`

## Champion / challenger

- Champion metadata: `models/v3/predictor/metadata_champion.json`
- Challenger backup before train: `models/v3/predictor_challenger_backup/`
- Decision log: `models/v3/predictor/promotion-decision.json`

Predictor only replaces production weights when AUC/accuracy improves statistically.

## NPU configuration

```bash
PREFER_NPU=true
# Force providers (optional):
ONNX_EXECUTION_PROVIDERS=QNNExecutionProvider,CPUExecutionProvider
```

Install NPU acceleration on Snapdragon Windows (pick one that matches your build):

```powershell
pip install onnxruntime-qnn
# or
pip install onnxruntime-directml
```

Then verify: `python scripts/npu_runtime.py` should list `QNNExecutionProvider` or `DmlExecutionProvider` in `selected`.

## State & logs

- `data/learning/harness_state.json` — last phase and step results
- `logs/harness-*.log` — full cycle logs
- `logs/autonomous-loop.log` — loop supervisor

## Environment

See `.env.example` — `LEARNING_LOOP_HOURS`, `SKIP_PREDICTOR_TRAIN`, `INSIDER_FETCH_LIMIT`.
