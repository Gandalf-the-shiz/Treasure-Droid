"""
pretrain-full-year.py

One-command pretraining workflow for next-day prediction over the last year,
using as much available data as possible.

Pipeline:
  1) Refresh 1-year historical OHLCV data
  2) Refresh macro snapshots from public FRED history
  3) Build features (strict public-data mode by default)
  4) Train model
  5) Generate daily predictions

Usage:
  python scripts/pretrain-full-year.py

Optional env vars:
  STRICT_PUBLIC_DATA=true|false        (default: true)
  PUBLIC_DATA_FORWARD_FILL_DAYS=0      (default: 0)
  MIN_PUBLIC_COVERAGE=0.30             (default: 0.30)
  MAX_TRAIN_SAMPLES=0                  (default: 0 = use all samples)
  TRAIN_BACKEND=auto|tensorflow|sklearn (default: auto)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run_step(label: str, args: list[str], env: dict[str, str]) -> None:
    print("=" * 72)
    print(f"[pretrain] {label}")
    print("=" * 72)
    cmd = [PYTHON] + args
    print("[pretrain] cmd:", " ".join(cmd))
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    if completed.returncode != 0:
        raise SystemExit(f"[pretrain] FAILED at step '{label}' (exit={completed.returncode})")


def assert_tensorflow_available(env: dict[str, str]) -> None:
    """Fail fast when TensorFlow is not available in the active interpreter."""
    cmd = [PYTHON, "-c", "import tensorflow as tf; print(tf.__version__)"]
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    if completed.returncode != 0:
        raise SystemExit(
            "[pretrain] TensorFlow is not available in this Python interpreter. "
            "Install a supported TensorFlow build or run this script with an interpreter "
            "that already has TensorFlow before starting pretraining."
        )


def module_available(module_name: str, env: dict[str, str]) -> bool:
    cmd = [PYTHON, "-c", f"import {module_name}"]
    completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env)
    return completed.returncode == 0


def resolve_training_backend(env: dict[str, str]) -> str:
    requested = env.get("TRAIN_BACKEND", "auto").strip().lower()
    if requested not in {"auto", "tensorflow", "sklearn"}:
        raise SystemExit(
            "[pretrain] Invalid TRAIN_BACKEND. Use one of: auto, tensorflow, sklearn."
        )

    has_tf = module_available("tensorflow", env)
    has_sklearn = module_available("sklearn", env)

    if requested == "tensorflow":
        if not has_tf:
            raise SystemExit(
                "[pretrain] TRAIN_BACKEND=tensorflow requested but TensorFlow is not installed."
            )
        return "tensorflow"

    if requested == "sklearn":
        if not has_sklearn:
            raise SystemExit(
                "[pretrain] TRAIN_BACKEND=sklearn requested but scikit-learn is not installed."
            )
        return "sklearn"

    if has_tf:
        return "tensorflow"
    if has_sklearn:
        return "sklearn"
    raise SystemExit(
        "[pretrain] Neither TensorFlow nor scikit-learn is available in this interpreter."
    )


def main() -> None:
    env = os.environ.copy()
    env.setdefault("STRICT_PUBLIC_DATA", "true")
    env.setdefault("PUBLIC_DATA_FORWARD_FILL_DAYS", "0")
    env.setdefault("MIN_PUBLIC_COVERAGE", "0.30")
    env.setdefault("MAX_TRAIN_SAMPLES", "0")
    env.setdefault("TRAIN_BACKEND", "auto")
    env["PYTHONPATH"] = "scripts"

    backend = resolve_training_backend(env)
    env["TRAIN_BACKEND"] = backend
    print(f"[pretrain] Using training backend: {backend}")

    run_step("Fetch tickers", ["scripts/fetch-tickers.py"], env)
    run_step("Fetch 1-year historical data", ["scripts/fetch-history.py", "--full-fetch"], env)
    run_step("Fetch macro public history snapshots", ["scripts/fetch-macro.py"], env)
    run_step("Build features", ["scripts/build-features.py"], env)
    if backend == "tensorflow":
        run_step("Train model (tensorflow)", ["scripts/train-model.py"], env)
    else:
        run_step("Train model (sklearn fallback)", ["scripts/train-model-sklearn.py"], env)
    run_step("Generate predictions", ["scripts/generate-predictions.py"], env)

    print("\n[pretrain] SUCCESS: full-year pretraining pipeline completed.")


if __name__ == "__main__":
    main()
