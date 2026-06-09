"""Unified intelligence pulse — run all learning + alt-data modules."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

STATUS_PATH = REPO / "data" / "intelligence" / "brain_status.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_full() -> dict:
    import subprocess
    py = sys.executable
    # Refresh SEC / congress canals before scoring (best-effort)
    for script in ("fetch-congress-trades.py", "fetch-insider-trades.py"):
        try:
            subprocess.run(
                [py, str(REPO / "scripts" / script), "--limit", "60"],
                cwd=str(REPO),
                timeout=900,
                check=False,
            )
        except Exception:
            pass

    from intelligence.mass_psychology import run as mass_run
    from intelligence.insider_monitor import run as insider_run
    from intelligence.execution_feedback import run as feedback_run
    from intelligence.forward_score import score_live
    from intelligence.champion_sync import run as sync_run
    from intelligence.arena.engine import run_active_pulses as arena_pulse

    results = {}
    results["massPsychology"] = mass_run()
    results["insiderMonitor"] = insider_run()
    results["executionFeedback"] = feedback_run()
    results["forwardScore"] = score_live()
    results["championSync"] = sync_run()
    results["traderArena"] = arena_pulse(100)
    try:
        from intelligence.real_agents import run_operating_cycle
        results["operatingCycle"] = run_operating_cycle(evolve=True)
    except Exception as exc:
        results["operatingCycle"] = {"error": str(exc)}

    # Profit gate
    try:
        import subprocess
        py = sys.executable
        subprocess.run([py, "scripts/paper-agent-profit-gate.py"], cwd=str(REPO), check=False)
        pg = REPO / "data" / "paper_agent" / "profit-gate.json"
        results["profitGate"] = json.loads(pg.read_text()) if pg.exists() else {}
    except Exception as exc:
        results["profitGate"] = {"error": str(exc)}

    doc = {"generatedAt": _now(), "results": results}
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="skip slow scrapers")
    args = ap.parse_args()
    if args.quick:
        from intelligence.execution_feedback import run as feedback_run
        from intelligence.champion_sync import run as sync_run
        doc = {"generatedAt": _now(), "quick": True,
                "executionFeedback": feedback_run(), "championSync": sync_run()}
        STATUS_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    else:
        doc = run_full()
    print(json.dumps(doc, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
