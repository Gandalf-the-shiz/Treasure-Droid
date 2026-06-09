"""Export the trained investor-v3 policy regressor to ONNX.

Standalone — loads `models/v3/investor/policy.joblib` (produced by
`train-investor-v3.py`) and writes `models/v3/investor/policy.onnx` plus a
small `policy.onnx.meta.json` describing the expected input layout.

Usage:
    python scripts/export_onnx.py             # export + parity check
    python scripts/export_onnx.py --bench     # also benchmark CPU EP vs joblib

The model is small (5-feature HistGradientBoostingRegressor), so the win on
CPU is modest — but the ONNX artifact is portable: the same file can later be
loaded by the browser (`onnxruntime-web`) so GitHub Pages can score picks
locally, or run on the Snapdragon NPU through the QNN execution provider.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import joblib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models" / "v3" / "investor"
PKL_PATH = MODEL_DIR / "policy.joblib"
ONNX_PATH = MODEL_DIR / "policy.onnx"
META_PATH = MODEL_DIR / "policy.onnx.meta.json"
VAL_CSV = ROOT / "data" / "predictions_v3" / "val.csv"

FEAT_COLS = ["pred_proba_up", "pred_ret", "sector_id", "edge", "confidence"]


def _load_val_sample(n: int = 256) -> np.ndarray | None:
    if not VAL_CSV.exists():
        return None
    import pandas as pd

    df = pd.read_csv(VAL_CSV)
    if "sector_id" not in df.columns:
        sectors = sorted(df["sector"].dropna().unique().tolist())
        sec_id = {s: i for i, s in enumerate(sectors)}
        df["sector_id"] = df["sector"].map(sec_id).fillna(-1).astype(int)
    if "edge" not in df.columns:
        df["edge"] = (df["pred_proba_up"] - 0.5) * 2.0 * df["pred_ret"]
    if "confidence" not in df.columns:
        df["confidence"] = (df["pred_proba_up"] - 0.5).abs() * 2.0
    return df[FEAT_COLS].head(n).to_numpy(dtype=np.float32)


def _patch_onnx_bool_int() -> None:
    """skl2onnx 1.20 emits Python bools where onnx 1.21 expects ints for the
    TreeEnsembleRegressor "nodes_missing_value_tracks_true" attribute. Coerce
    bool → int before the proto extends. Safe no-op on older onnx versions."""
    import onnx.helper as _h

    if getattr(_h, "_nostra_patched", False):
        return
    _orig = _h.make_attribute

    def _coerce(*args, **kwargs):
        # signature: make_attribute(key, value, doc_string=None, attr_type=...)
        if len(args) >= 2:
            key, value = args[0], args[1]
            rest = args[2:]
        else:
            key = kwargs.get("key")
            value = kwargs.pop("value", None)
            rest = ()
        if value is not None and not isinstance(value, (str, bytes, int, float)):
            try:
                seq = list(value)
                if seq and any(isinstance(v, bool) for v in seq):
                    value = [int(v) if isinstance(v, bool) else v for v in seq]
            except TypeError:
                pass
        return _orig(key, value, *rest, **kwargs)

    _h.make_attribute = _coerce
    _h._nostra_patched = True  # type: ignore[attr-defined]


def export() -> Path:
    _patch_onnx_bool_int()
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    if not PKL_PATH.exists():
        sys.exit(f"missing model: {PKL_PATH} — run scripts/train-investor-v3.py first")
    policy = joblib.load(PKL_PATH)
    initial_type = [("float_input", FloatTensorType([None, len(FEAT_COLS)]))]
    onnx_model = convert_sklearn(
        policy,
        initial_types=initial_type,
        target_opset=18,
        options={id(policy): {"zipmap": False}} if hasattr(policy, "classes_") else None,
    )
    ONNX_PATH.write_bytes(onnx_model.SerializeToString())
    META_PATH.write_text(
        json.dumps(
            {
                "input_name": "float_input",
                "input_shape": ["batch", len(FEAT_COLS)],
                "dtype": "float32",
                "feature_order": FEAT_COLS,
                "model_class": type(policy).__name__,
                "exported_with": "skl2onnx",
            },
            indent=2,
        )
    )
    print(f"[export] wrote {ONNX_PATH.relative_to(ROOT)} ({ONNX_PATH.stat().st_size/1024:.1f} KiB)")
    return ONNX_PATH


def parity_check(rtol: float = 1e-4, atol: float = 1e-5) -> None:
    import onnxruntime as ort

    policy = joblib.load(PKL_PATH)
    X = _load_val_sample(256)
    if X is None:
        rng = np.random.default_rng(0)
        X = rng.standard_normal((256, len(FEAT_COLS))).astype(np.float32)
    sess = ort.InferenceSession(str(ONNX_PATH), providers=["CPUExecutionProvider"])
    onnx_out = sess.run(None, {"float_input": X})[0].reshape(-1)
    pkl_out = policy.predict(X).astype(np.float32).reshape(-1)
    max_abs = float(np.max(np.abs(onnx_out - pkl_out)))
    max_rel = float(np.max(np.abs(onnx_out - pkl_out) / (np.abs(pkl_out) + 1e-9)))
    ok = np.allclose(onnx_out, pkl_out, rtol=rtol, atol=atol)
    print(f"[parity] samples={len(X)} max_abs_err={max_abs:.2e} max_rel_err={max_rel:.2e} ok={ok}")
    if not ok:
        sys.exit(1)


def benchmark(iters: int = 50) -> None:
    import onnxruntime as ort

    policy = joblib.load(PKL_PATH)
    X = _load_val_sample(4096)
    if X is None:
        X = np.random.default_rng(0).standard_normal((4096, len(FEAT_COLS))).astype(np.float32)

    t0 = time.perf_counter()
    for _ in range(iters):
        policy.predict(X)
    pkl_ms = (time.perf_counter() - t0) * 1000 / iters

    sess = ort.InferenceSession(str(ONNX_PATH), providers=["CPUExecutionProvider"])
    feeds = {"float_input": X}
    for _ in range(5):
        sess.run(None, feeds)
    t0 = time.perf_counter()
    for _ in range(iters):
        sess.run(None, feeds)
    onnx_ms = (time.perf_counter() - t0) * 1000 / iters

    print(f"[bench] batch={len(X)} joblib={pkl_ms:.2f} ms  onnx-cpu={onnx_ms:.2f} ms  speedup={pkl_ms/onnx_ms:.2f}x")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="store_true", help="run a CPU benchmark vs joblib")
    ap.add_argument("--skip-parity", action="store_true")
    args = ap.parse_args()
    export()
    if not args.skip_parity:
        parity_check()
    if args.bench:
        benchmark()


if __name__ == "__main__":
    main()
