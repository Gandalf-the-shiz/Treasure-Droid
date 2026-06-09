"""Live-trading readiness gate bridge (source-repo side).

The honest evaluation, forward paper PnL, and risk checks live in the companion
``nostradamus-live`` repo, whose harness writes a single go/no-go decision to
``data/gate/readiness.json``. This module reads that decision and FORCES every
manifest into dryRun/paper mode unless live trading is explicitly permitted.

Fail-safe by design: if the decision file is missing or unreadable, we default
to NO-GO. Real trading can never be enabled by accident or by a stale file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def _live_root() -> Path:
    return Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))


def read_decision() -> dict:
    path = _live_root() / "data" / "gate" / "readiness.json"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        d.setdefault("liveTradingPermitted", False)
        d.setdefault("reasons", [])
        return d
    except (OSError, json.JSONDecodeError):
        return {
            "liveTradingPermitted": False,
            "reasons": [f"readiness decision not found at {path} — defaulting to NO-GO"],
        }


def enforce(manifest: dict) -> dict:
    """Stamp the readiness decision and force paper mode unless permitted."""
    d = read_decision()
    manifest["liveReadiness"] = {
        "liveTradingPermitted": bool(d.get("liveTradingPermitted")),
        "reasons": d.get("reasons", []),
        "checkedAt": d.get("generatedAt"),
    }
    if not d.get("liveTradingPermitted"):
        manifest["dryRun"] = True
        manifest["mode"] = "paper"
        risk = manifest.setdefault("risk", {})
        notes = risk.setdefault("notes", [])
        notes.append("LIVE TRADING BLOCKED by readiness gate: "
                     + "; ".join(d.get("reasons", []) or ["no-go"]))
    return manifest
