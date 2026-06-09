"""Nostradamus pipeline orchestrator — autonomous prep for live trading.

Runs the intelligence loop in order, respecting data-feed health gates.

Usage:
  python scripts/orchestrator.py                    # full nightly prep
  python scripts/orchestrator.py --steps feeds,macro,regime,investor,signals
  python scripts/orchestrator.py --skip-train-predictor
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
LOG_DIR = REPO / "logs"
HEALTH_PATH = REPO / "data" / "feeds" / "health.json"

STEPS = {
    "feeds": ["scripts/verify-data-feeds.py"],
    "macro": ["scripts/fetch-macro.py"],
    "regime": ["scripts/fetch-regime-data.py"],
    "history": ["scripts/fetch-history.py"],
    "predictor": ["scripts/train-predictor-v3.py"],
    "investor": ["scripts/train-investor-v3.py", "--top-k", "5", "--max-position-frac", "0.20",
                  "--max-gross-exposure", "0.90", "--kelly-scale", "0.5", "--cost-bps", "5",
                  "--slippage-bps", "10", "--min-proba", "0.60", "--min-pred-ret", "0.020",
                  "--min-price", "5", "--min-adv", "1000000", "--min-vol-20", "0.01",
                  "--max-daily-ret", "0.20", "--policy-mode", "edge"],
    "enrich": ["scripts/enrich_decisions.py", "--last-days", "10"],
    "signals": ["scripts/generate_trade_signals.py"],
    "congress": ["scripts/fetch-congress-trades.py"],
    "enrich_congress": ["scripts/enrich_congress_decisions.py"],
}

DEFAULT_ORDER = ["feeds", "macro", "regime", "congress", "insider", "history", "investor", "enrich", "enrich_congress", "signals"]

# Full autonomous stack — prefer learning_harness.py for always-on ML
HARNESS_CMD = ["scripts/learning_harness.py", "--once"]


def _run(cmd: list[str], log: Path) -> int:
    line = f"\n# {' '.join(cmd)}\n"
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        proc = subprocess.run([PYTHON] + cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT)
    return proc.returncode


def _health_ok() -> bool:
    if not HEALTH_PATH.exists():
        return True
    try:
        h = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        return bool(h.get("criticalReady", True))
    except Exception:
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="", help="comma-separated step names")
    ap.add_argument("--skip-train-predictor", action="store_true")
    ap.add_argument("--require-healthy-feeds", action="store_true",
                    default=os.getenv("ORCHESTRATOR_REQUIRE_HEALTH", "true").lower() in {"1", "true", "yes"})
    args = ap.parse_args()

    order = [s.strip() for s in args.steps.split(",") if s.strip()] if args.steps else list(DEFAULT_ORDER)
    if args.skip_train_predictor and "predictor" in order:
        order.remove("predictor")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = LOG_DIR / f"orchestrator-{stamp}.log"
    log.write_text(f"# nostradamus orchestrator @ {stamp}\n", encoding="utf-8")

    results: dict[str, int] = {}
    for step in order:
        if step not in STEPS:
            print(f"[orchestrator] unknown step: {step}", flush=True)
            results[step] = 2
            continue
        if step != "feeds" and args.require_healthy_feeds and not _health_ok():
            print("[orchestrator] abort: data feeds not criticalReady", flush=True)
            return 1
        if step == "predictor" and os.getenv("SKIP_PREDICTOR_TRAIN", "").lower() in {"1", "true", "yes"}:
            print("[orchestrator] skip predictor (SKIP_PREDICTOR_TRAIN)", flush=True)
            continue
        t0 = time.time()
        rc = _run(STEPS[step], log)
        results[step] = rc
        print(f"[orchestrator] {step} exit={rc} ({time.time()-t0:.1f}s)", flush=True)
        if step == "feeds" and rc != 0:
            return rc
        if step == "investor" and rc != 0:
            return rc

    summary = {"finishedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "steps": results}
    (REPO / "data" / "trading" / "orchestrator_last.json").parent.mkdir(parents=True, exist_ok=True)
    (REPO / "data" / "trading" / "orchestrator_last.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    failed = [k for k, v in results.items() if v != 0]
    if failed:
        print(f"[orchestrator] completed with failures: {failed}")
        return 1
    print("[orchestrator] all steps OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
