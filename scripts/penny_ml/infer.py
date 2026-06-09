"""NPU-accelerated ONNX inference for Penny Wolf champion."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .config import CHAMPION_ONNX, ONNX_META, NPU_PROVIDER_PRIORITY

_SESSION_CACHE = None
_META_CACHE = None


def _providers() -> list[str]:
    try:
        from npu_runtime import available_providers, ensure_qnn_registered, qnn_devices
        ensure_qnn_registered()
        if qnn_devices():
            return [p for p in NPU_PROVIDER_PRIORITY if p == "QNNExecutionProvider"] + ["CPUExecutionProvider"]
        return available_providers()
    except ImportError:
        try:
            import onnxruntime as ort
            return list(ort.get_available_providers())
        except ImportError:
            return []


def load_session():
    global _SESSION_CACHE, _META_CACHE
    if _SESSION_CACHE is not None:
        return _SESSION_CACHE, _META_CACHE
    if not CHAMPION_ONNX.exists():
        return None, None
    meta = {}
    if ONNX_META.exists():
        meta = json.loads(ONNX_META.read_text(encoding="utf-8"))
    try:
        from npu_runtime import create_inference_session
        sess = create_inference_session(CHAMPION_ONNX)
    except ImportError:
        import onnxruntime as ort
        sess = ort.InferenceSession(str(CHAMPION_ONNX), providers=["CPUExecutionProvider"])
    _SESSION_CACHE, _META_CACHE = sess, meta
    return sess, meta


def predict_matrix(X: np.ndarray) -> np.ndarray:
    """X: (n, n_features) float32. Returns score vector."""
    sess, meta = load_session()
    if sess is None:
        return np.full(len(X), np.nan)
    name = meta.get("input_name") or sess.get_inputs()[0].name
    X = np.asarray(X, dtype=np.float32)
    out = sess.run(None, {name: X})[0]
    if out.ndim > 1:
        out = out[:, 0] if out.shape[1] == 1 else out.ravel()
    return out.astype(np.float64)


def export_champion_onnx(model, feature_cols: list[str]) -> dict:
    """Export sklearn model to ONNX for NPU inference."""
    from .config import CHAMPION_ONNX, MODEL_DIR, ONNX_META
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
        onnx_model = convert_sklearn(
            model,
            initial_types=[("float_input", FloatTensorType([None, len(feature_cols)]))],
            target_opset=18,
        )
        CHAMPION_ONNX.write_bytes(onnx_model.SerializeToString())
        meta = {
            "input_name": "float_input",
            "feature_order": feature_cols,
            "providers": _providers(),
            "primary": _providers()[0] if _providers() else "none",
        }
        ONNX_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return {"ok": True, "path": str(CHAMPION_ONNX), "primary": meta["primary"]}
    except Exception as exc:
        msg = str(exc)
        if len(msg) > 400:
            msg = msg[:400] + "..."
        return {"ok": False, "error": msg}
