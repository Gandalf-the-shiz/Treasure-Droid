"""Daily forward step for the whole crew.

Builds the shared signal frame once, then walks every registered agent forward
one day (mark + rebalance + document), and writes a fleet summary the captain
and dashboard read.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SUMMARY_PATH = REPO / "data" / "fleet" / "summary.json"

import sys

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.alpha.engine import build_alpha_frame  # noqa: E402
from intelligence.fleet import paper, registry  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run() -> dict:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    df, sleeves_used, cfg = build_alpha_frame()
    if df is None or df.empty:
        doc = {"generatedAt": _now(), "ok": False, "message": "no signal frame (run generate_live_predictions)"}
        SUMMARY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print("[fleet] no signal frame", flush=True)
        return doc

    sleeve_cols = [f"n_{s}" for s in sleeves_used]
    date = str(df["date"].max()) if "date" in df.columns else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    reg = registry.load_registry()
    results = []
    for agent in reg.get("agents", []):
        try:
            results.append(paper.step_agent(agent, df, date, sleeve_cols, cfg,
                                            starting_cash=float(agent.get("capital", 100000.0))))
        except Exception as exc:  # noqa: BLE001
            results.append({"id": agent.get("id"), "name": agent.get("name"),
                            "kind": agent.get("kind"), "error": str(exc)[:200]})

    ranked = sorted([r for r in results if "equity" in r], key=lambda r: r.get("returnPct", -1e9), reverse=True)
    doc = {
        "generatedAt": _now(), "ok": True, "date": date,
        "universe": int(len(df)), "sleeves": sleeves_used,
        "nAgents": len(results), "agents": ranked,
        "errors": [r for r in results if "error" in r],
        "leader": ranked[0] if ranked else None,
    }
    SUMMARY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lead = doc["leader"]
    print(f"[fleet] {len(ranked)} agents stepped @ {date}; "
          f"leader={lead['name'] if lead else '-'} "
          f"({lead['returnPct'] if lead else 0:+.2f}%)", flush=True)
    return doc


if __name__ == "__main__":
    run()
