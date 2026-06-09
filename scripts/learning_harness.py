"""Autonomous continuous learning harness for Nostradamus.

Runs the full intelligence loop: data canals → ML train → promote → investor →
NPU sentiment enrich → Robinhood manifest. Designed for local always-on loops
(see scripts/autonomous_loop.ps1).

Usage:
  python scripts/learning_harness.py
  python scripts/learning_harness.py --once
  python scripts/learning_harness.py --loop-hours 24
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
LOG_DIR = REPO / "logs"
STATE_PATH = REPO / "data" / "learning" / "harness_state.json"
PRED_DIR = REPO / "models" / "v3" / "predictor"
BACKUP_DIR = REPO / "models" / "v3" / "predictor_challenger_backup"

INVESTOR_ARGS = [
    "scripts/train-investor-v3.py",
    "--top-k", "5", "--max-position-frac", "0.20", "--max-gross-exposure", "0.90",
    "--kelly-scale", "0.5", "--cost-bps", "5", "--slippage-bps", "10",
    "--min-proba", "0.60", "--min-pred-ret", "0.020", "--min-price", "5",
    "--min-adv", "1000000", "--min-vol-20", "0.01", "--max-daily-ret", "0.20",
    "--policy-mode", "edge",
]


def _run(cmd: list[str], log: Path) -> int:
    line = f"\n# {datetime.now(timezone.utc).isoformat()} {' '.join(cmd)}\n"
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        return subprocess.run([PYTHON] + cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT).returncode


def _write_state(patch: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state.update(patch)
    state["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _backup_champion() -> None:
    if not PRED_DIR.exists():
        return
    if BACKUP_DIR.exists():
        shutil.rmtree(BACKUP_DIR, ignore_errors=True)
    shutil.copytree(PRED_DIR, BACKUP_DIR, dirs_exist_ok=True)


def run_cycle(log: Path, train_predictor: bool, mode: str = "weekly") -> int:
    sys.path.insert(0, str(REPO / "scripts"))
    from npu_runtime import write_status

    npu_path = write_status()
    _write_state({"phase": "starting", "npu": json.loads(npu_path.read_text())})

    steps: list[tuple[str, list[str]]] = [
        ("npu_probe", ["scripts/npu_runtime.py"]),
        ("feeds", ["scripts/verify-data-feeds.py"]),
        ("macro", ["scripts/fetch-macro.py"]),
        ("regime", ["scripts/fetch-regime-data.py"]),
        ("congress", ["scripts/fetch-congress-trades.py"]),
        ("insider", ["scripts/fetch-insider-trades.py"]),
        ("mass_psych", ["scripts/intelligence/mass_psychology.py"]),
        ("insider_monitor", ["scripts/intelligence/insider_monitor.py"]),
        ("history", ["scripts/fetch-history.py"]),
    ]

    skip_pred = os.getenv("SKIP_PREDICTOR_TRAIN", "").lower() in {"1", "true", "yes"}
    if mode == "daily":
        train_predictor = False
    elif mode == "intraday":
        train_predictor = False
        steps = [
            ("npu_probe", ["scripts/npu_runtime.py"]),
            ("regime", ["scripts/fetch-regime-data.py"]),
            ("congress", ["scripts/fetch-congress-trades.py"]),
            ("mass_psych", ["scripts/intelligence/mass_psychology.py"]),
            ("insider_monitor", ["scripts/intelligence/insider_monitor.py"]),
            ("live_pred", ["scripts/generate_live_predictions.py", "--limit", os.getenv("LIVE_PREDICT_LIMIT", "2500")]),
            ("alpha_engine", ["scripts/intelligence/alpha/engine.py"]),
            ("fleet", ["scripts/intelligence/fleet/run.py"]),
            ("champion_sync", ["scripts/intelligence/champion_sync.py"]),
            ("forward_score", ["scripts/intelligence/forward_score.py"]),
            ("execution_feedback", ["scripts/intelligence/execution_feedback.py"]),
            ("reasoning", ["scripts/reasoning_agent.py", "--tick"]),
            ("daytrade", ["scripts/generate_daytrade_signals.py"]),
        ]
        SOFT_FAIL = {
            "regime", "congress", "mass_psych", "insider_monitor", "live_pred",
            "alpha_engine", "fleet", "champion_sync", "forward_score", "execution_feedback",
            "reasoning", "daytrade",
        }
        results: dict[str, int] = {}
        for name, cmd in steps:
            _write_state({"phase": name, "mode": mode})
            rc = _run(cmd, log)
            results[name] = rc
            print(f"[harness] {name} rc={rc}", flush=True)
        _write_state({"phase": "complete", "mode": mode, "results": results, "log": log.name})
        _sync_scheduler(mode)
        _log_harness_journal(mode, results, log)
        return 0

    if train_predictor and not skip_pred:
        steps.append(("train_predictor", ["scripts/train-predictor-v3.py"]))

    steps.extend([
        ("promote_predictor", ["scripts/promotion_gate_v3.py"]),
        ("investor", INVESTOR_ARGS),
        ("promote_investor", ["scripts/promotion_gate_investor.py"]),
        ("enrich_sentiment", ["scripts/enrich_decisions.py", "--last-days", "10"]),
        ("enrich_congress", ["scripts/enrich_congress_decisions.py", "--last-days", "30"]),
        ("champion_sync", ["scripts/intelligence/champion_sync.py"]),
        ("forward_score", ["scripts/intelligence/forward_score.py"]),
        ("finnhub", ["scripts/fetch_finnhub.py"]),
        ("sentiment_feed", ["scripts/fetch_sentiment_feed.py"]),
        ("alpha_engine", ["scripts/intelligence/alpha/engine.py"]),
        ("alpha_measure", ["scripts/intelligence/alpha/measure.py"]),
        ("sleeve_ic", ["scripts/intelligence/alpha/sleeve_ic.py"]),
        ("mad_scientist_lab", ["scripts/intelligence/historical/walkforward_lab.py", "--rebuild-panel", "--genomes", "500", "--promote", "5"]),
        ("fleet", ["scripts/intelligence/fleet/run.py"]),
        ("execution_feedback", ["scripts/intelligence/execution_feedback.py"]),
        ("profit_gate", ["scripts/paper-agent-profit-gate.py"]),
        ("signals", ["scripts/generate_trade_signals.py"]),
        ("reasoning", ["scripts/reasoning_agent.py", "--tick"]),
        ("brain", ["scripts/intelligence/brain.py", "--quick"]),
        ("trader_arena", ["scripts/intelligence/trader_arena.py", "--pulse"]),
    ])
    if mode in {"weekly", "full", "daily", "intraday"}:
        steps.append(("daytrade", ["scripts/generate_daytrade_signals.py"]))
    if mode in {"weekly", "full"}:
        steps.append(("walk_forward", ["scripts/intelligence/fleet/backtest.py", "--genomes", "200", "--promote", "2"]))

    SOFT_FAIL = {
        "macro", "insider", "history", "regime", "mass_psych", "insider_monitor",
        "promote_predictor", "promote_investor", "champion_sync", "forward_score",
        "finnhub", "sentiment_feed", "alpha_engine", "alpha_measure", "sleeve_ic", "mad_scientist_lab", "fleet", "walk_forward",
        "execution_feedback", "profit_gate", "reasoning", "daytrade", "brain", "trader_arena",
    }
    results: dict[str, int] = {}
    for name, cmd in steps:
        _write_state({"phase": name, "mode": mode})
        if name == "train_predictor":
            _backup_champion()
        t0 = time.time()
        rc = _run(cmd, log)
        results[name] = rc
        print(f"[harness] {name} rc={rc} ({time.time()-t0:.0f}s)", flush=True)
        if name == "feeds" and rc != 0:
            _write_state({"phase": "failed", "results": results, "failedStep": name})
            return rc
        if name in SOFT_FAIL and rc != 0:
            print(f"[harness] soft-fail {name} — continuing", flush=True)
        if name == "promote_predictor" and rc != 0:
            print("[harness] predictor challenger not promoted — champion restored", flush=True)
        if name == "promote_investor" and rc != 0:
            print("[harness] investor challenger not promoted — champion restored", flush=True)
        if name == "investor" and rc != 0:
            _write_state({"phase": "failed", "results": results, "failedStep": name})
            return rc

    _maybe_retrain_from_forward_triggers(log, train_predictor)
    _write_state({"phase": "complete", "mode": mode, "results": results, "log": log.name})
    _sync_scheduler(mode)
    _log_harness_journal(mode, results, log)
    print("[harness] cycle complete", flush=True)
    return 0


def _log_harness_journal(mode: str, results: dict, log: Path) -> None:
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from intelligence.brain.journal import log_harness_cycle
        log_harness_cycle(mode=mode, results=results, log_name=log.name)
    except Exception as exc:
        print(f"[brain-journal] skip harness log: {exc}", flush=True)


def _maybe_retrain_from_forward_triggers(log: Path, train_predictor: bool) -> None:
    triggers_path = REPO / "data" / "learning" / "retrain_triggers.json"
    if not triggers_path.exists():
        return
    try:
        t = json.loads(triggers_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if t.get("triggerInvestorRetrain"):
        print("[harness] forward trigger: investor retrain", flush=True)
        _run(INVESTOR_ARGS, log)
        _run(["scripts/promotion_gate_investor.py"], log)
    if t.get("triggerPredictorRetrain") and train_predictor:
        print("[harness] forward trigger: predictor retrain", flush=True)
        _backup_champion()
        _run(["scripts/train-predictor-v3.py"], log)
        _run(["scripts/promotion_gate_v3.py"], log)


def _sync_scheduler(mode: str) -> None:
    """Record harness completion in scheduler_state so the brain loop knows."""
    key_map = {
        "intraday": "last_intraday_pulse",
        "daily": "last_daily_close",
        "weekly": "last_weekly_deep",
        "full": "last_weekly_deep",
    }
    key = key_map.get(mode)
    if not key:
        return
    sched_path = REPO / "data" / "learning" / "scheduler_state.json"
    sched_path.parent.mkdir(parents=True, exist_ok=True)
    state: dict = {}
    if sched_path.exists():
        try:
            state = json.loads(sched_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["lastHarnessMode"] = mode
    sched_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="single cycle (default)")
    ap.add_argument("--loop-hours", type=float, default=0.0, help="repeat every N hours (0=once)")
    ap.add_argument("--skip-predictor", action="store_true")
    ap.add_argument("--mode", choices=["full", "weekly", "daily", "intraday"], default="weekly")
    args = ap.parse_args()

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _one() -> int:
        log = LOG_DIR / f"harness-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
        log.write_text(f"# learning harness @ {datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
        train = not args.skip_predictor and args.mode in {"full", "weekly"}
        return run_cycle(log, train_predictor=train, mode=args.mode)

    if args.loop_hours <= 0:
        return _one()

    interval = max(args.loop_hours, 1.0) * 3600.0
    print(f"[harness] autonomous loop every {args.loop_hours}h — Ctrl+C to stop", flush=True)
    while True:
        rc = _one()
        if rc != 0:
            print(f"[harness] cycle failed rc={rc}, sleeping anyway", flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n[harness] stopped")
        raise SystemExit(0)
