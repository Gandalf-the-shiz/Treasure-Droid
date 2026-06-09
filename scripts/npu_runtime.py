"""ONNX Runtime provider selection — Snapdragon NPU (QNN plugin EP) first.

QNN EP 2.x is a *plugin* library: it must be registered via
``register_execution_provider_library`` before sessions can use the Hexagon NPU.
Importing ``onnxruntime_qnn`` alone does not add QNN to ``get_available_providers()``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STATUS_PATH = REPO / "data" / "learning" / "npu_status.json"

QNN_EP = "QNNExecutionProvider"

PROVIDER_PRIORITY = (
    QNN_EP,
    "DmlExecutionProvider",
    "CUDAExecutionProvider",
    "CPUExecutionProvider",
)

_qnn_registered = False


def ensure_qnn_registered() -> bool:
    """Register the QNN plugin EP with ONNX Runtime (idempotent)."""
    global _qnn_registered
    if _qnn_registered:
        return True
    try:
        import onnxruntime as ort
        import onnxruntime_qnn as qnn_ep

        ort.register_execution_provider_library(QNN_EP, qnn_ep.get_library_path())
        _qnn_registered = True
        return True
    except Exception:
        return False


def qnn_htp_options(extra: dict[str, Any] | None = None) -> dict[str, str]:
    import onnxruntime_qnn as qnn_ep

    opts = {"backend_path": qnn_ep.get_qnn_htp_path()}
    if extra:
        opts.update({k: str(v) for k, v in extra.items()})
    return opts


def qnn_devices() -> list:
    import onnxruntime as ort

    if not ensure_qnn_registered():
        return []
    return [d for d in ort.get_ep_devices() if d.ep_name == QNN_EP]


def available_providers() -> list[str]:
    try:
        import onnxruntime as ort
    except ImportError:
        return ["CPUExecutionProvider"]

    base = list(ort.get_available_providers())
    if qnn_devices() and QNN_EP not in base:
        return [QNN_EP, *base]
    return base


def select_providers() -> list[str]:
    forced = os.getenv("ONNX_EXECUTION_PROVIDERS", "").strip()
    if forced:
        return [p.strip() for p in forced.split(",") if p.strip()]
    avail = set(available_providers())
    return [p for p in PROVIDER_PRIORITY if p in avail] or ["CPUExecutionProvider"]


def primary_provider() -> str:
    ps = select_providers()
    return ps[0] if ps else "CPUExecutionProvider"


def create_inference_session(
    model_path: str | Path,
    *,
    sess_options=None,
    qnn_options: dict[str, Any] | None = None,
    allow_cpu_fallback: bool = True,
):
    """Create an ONNX Runtime session preferring Snapdragon NPU (QNN HTP)."""
    import onnxruntime as ort

    path = Path(model_path)
    opts = sess_options or ort.SessionOptions()
    forced = os.getenv("ONNX_EXECUTION_PROVIDERS", "").strip()
    force_list = [p.strip() for p in forced.split(",") if p.strip()] if forced else None

    want_qnn = (not force_list) or (QNN_EP in force_list)
    devices = qnn_devices() if want_qnn else []

    if devices:
        ep_opts = qnn_htp_options(qnn_options)
        opts.add_provider_for_devices(devices, ep_opts)
        try:
            return ort.InferenceSession(str(path), sess_options=opts)
        except Exception:
            if not allow_cpu_fallback:
                raise
            # Rebuild session without QNN devices (CPU only)
            opts = sess_options or ort.SessionOptions()

    # Legacy provider list (DML / CPU)
    providers: list = []
    avail = set(ort.get_available_providers())
    order = force_list or [p for p in PROVIDER_PRIORITY if p != QNN_EP]
    for ep in order:
        if ep == QNN_EP:
            continue
        if ep in avail:
            if ep == "DmlExecutionProvider":
                providers.append((ep, {}))
            else:
                providers.append(ep)
    if not providers:
        providers = ["CPUExecutionProvider"]
    elif allow_cpu_fallback and "CPUExecutionProvider" in avail:
        if not any(p == "CPUExecutionProvider" or (isinstance(p, tuple) and p[0] == "CPUExecutionProvider")
                   for p in providers):
            providers.append("CPUExecutionProvider")
    return ort.InferenceSession(str(path), sess_options=opts, providers=providers)


def write_status(extra: dict | None = None) -> Path:
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    devices = qnn_devices()
    doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "qnnRegistered": ensure_qnn_registered(),
        "qnnDevices": len(devices),
        "available": available_providers(),
        "selected": select_providers(),
        "primary": primary_provider(),
        "preferNpu": os.getenv("PREFER_NPU", "true").lower() in {"1", "true", "yes"},
        "soc": "Snapdragon X (X1P64100)",
        "qnnPackage": _qnn_package_version(),
    }
    if extra:
        doc.update(extra)
    STATUS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return STATUS_PATH


def _qnn_package_version() -> str | None:
    try:
        import onnxruntime_qnn as qnn_ep
        return getattr(qnn_ep, "__version__", None)
    except ImportError:
        return None


if __name__ == "__main__":
    p = write_status()
    print(json.dumps(json.loads(p.read_text()), indent=2))
