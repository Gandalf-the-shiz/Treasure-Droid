"""Market-aware scheduler — picks the right learning cycle for maximum profit cadence.

Modes:
  intraday_pulse  — every 15m during RTH: live quotes, reasoning, daytrade manifest
  daily_close     — once after 4:15pm ET: data canals, investor, swing manifest
  weekly_deep     — Sunday evening: full predictor retrain + dual promotion

Usage:
  python scripts/learning_scheduler.py --tick     # run due work + print sleep hint
  python scripts/learning_scheduler.py --status
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
STATE_PATH = REPO / "data" / "learning" / "scheduler_state.json"
SCHEDULE_PATH = REPO / "data" / "learning" / "schedule.json"

sys.path.insert(0, str(REPO / "scripts"))
from market_clock import is_after_close, is_market_open, is_weekday, now_et, session_label  # noqa: E402


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _hours_since(state: dict, key: str) -> float:
    ts = state.get(key)
    if not ts:
        return 1e9
    try:
        t0 = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - t0).total_seconds() / 3600.0
    except Exception:
        return 1e9


def decide_mode(state: dict) -> tuple[str, int]:
    """Return (mode, recommended_sleep_seconds)."""
    et = now_et()
    intraday_min = float(os.getenv("INTRADAY_PULSE_MINUTES", "15"))
    daily_hours = float(os.getenv("DAILY_CLOSE_HOURS", "22"))
    weekly_hours = float(os.getenv("WEEKLY_DEEP_HOURS", "168"))

    if et.weekday() == 6 and _hours_since(state, "last_weekly_deep") >= weekly_hours:
        return "weekly_deep", 3600

    if is_market_open(et) and _hours_since(state, "last_intraday_pulse") * 60 >= intraday_min:
        return "intraday_pulse", int(intraday_min * 60)

    if is_weekday(et) and is_after_close(et) and _hours_since(state, "last_daily_close") >= daily_hours:
        return "daily_close", 1800

    if is_market_open(et):
        wait = max(60, int(intraday_min * 60 - _hours_since(state, "last_intraday_pulse") * 3600))
        return "idle_market", wait
    if is_weekday(et) and not is_after_close(et):
        return "idle_premarket", 600
    return "idle_offhours", 1800


def run_mode(mode: str, log: Path) -> int:
    cmds: list[list[str]] = []
    if mode == "intraday_pulse":
        cmds = [
            ["scripts/npu_runtime.py"],
            ["scripts/fetch-regime-data.py"],
            ["scripts/fetch-congress-trades.py"],
            ["scripts/generate_live_predictions.py", "--limit", os.getenv("LIVE_PREDICT_LIMIT", "800")],
            ["scripts/reasoning_agent.py", "--tick"],
            ["scripts/generate_daytrade_signals.py"],
        ]
    elif mode == "daily_close":
        cmds = [
            ["scripts/learning_harness.py", "--once", "--mode", "daily"],
        ]
    elif mode == "weekly_deep":
        cmds = [
            ["scripts/learning_harness.py", "--once", "--mode", "weekly"],
        ]
    else:
        return 0

    rc = 0
    with open(log, "a", encoding="utf-8") as fh:
        for cmd in cmds:
            fh.write(f"\n# {datetime.now(timezone.utc).isoformat()} {' '.join(cmd)}\n")
            fh.flush()
            r = subprocess.run([PYTHON] + cmd, cwd=str(REPO), stdout=fh, stderr=subprocess.STDOUT)
            if r.returncode != 0 and mode != "intraday_pulse":
                rc = r.returncode
            elif r.returncode != 0:
                fh.write(f"# soft-fail {cmd[0]} rc={r.returncode}\n")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tick", action="store_true", help="execute due cycle")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args()

    state = _load_state()
    mode, sleep_s = decide_mode(state)

    doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session": session_label(),
        "recommendedMode": mode,
        "sleepSeconds": sleep_s,
        "lastRuns": {
            "intraday_pulse": state.get("last_intraday_pulse"),
            "daily_close": state.get("last_daily_close"),
            "weekly_deep": state.get("last_weekly_deep"),
        },
    }
    SCHEDULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    if args.status or not args.tick:
        print(json.dumps(doc, indent=2))
        if not args.tick:
            return 0

    log = REPO / "logs" / f"scheduler-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    log.write_text(f"# scheduler mode={mode}\n", encoding="utf-8")
    rc = run_mode(mode, log)
    key = f"last_{mode}" if mode in {"intraday_pulse", "daily_close", "weekly_deep"} else None
    if key:
        state[key] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state["lastMode"] = mode
    state["lastRc"] = rc
    _save_state(state)
    print(f"[scheduler] mode={mode} rc={rc} next_sleep={sleep_s}s session={doc['session']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
