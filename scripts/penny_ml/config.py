"""Paths and defaults for Penny Wolf ML."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HIST = REPO / "data" / "historical"
ML_DIR = REPO / "data" / "penny" / "ml"
MODEL_DIR = REPO / "models" / "penny"
PANEL_CACHE = ML_DIR / "panel.parquet"
LEDGER = ML_DIR / "trials.jsonl"
CHAMPION = ML_DIR / "champion.json"
CHAMPION_JOBLIB = MODEL_DIR / "champion.joblib"
CHAMPION_ONNX = MODEL_DIR / "champion.onnx"
ONNX_META = MODEL_DIR / "champion.onnx.meta.json"
STATUS = ML_DIR / "search_status.json"

MAX_PRICE = 5.0
MIN_PRICE = 0.25
MIN_ADV20 = 50_000.0
START_DATE = "2015-01-01"
NPU_PROVIDER_PRIORITY = ("QNNExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider")
