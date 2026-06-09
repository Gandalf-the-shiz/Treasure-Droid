"""Sync nostradamus-live auto_search champion into audit-repo intelligence overlay."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))
CHAMPION_SRC = LIVE_ROOT / "reports" / "auto_search" / "champion.json"
OVERLAY_PATH = REPO / "data" / "intelligence" / "live_champion_overlay.json"
TILT_PATH = REPO / "data" / "predictions_v3" / "champion_tilt.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run() -> dict:
    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CHAMPION_SRC.exists():
        doc = {"generatedAt": _now(), "synced": False, "message": "no live champion.json"}
        OVERLAY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return doc

    try:
        champ = json.loads(CHAMPION_SRC.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"synced": False, "error": str(exc)}

    cfg = champ.get("config") or {}
    metrics = champ.get("metrics") or champ.get("oos_metrics") or {}
    overlay = {
        "generatedAt": _now(),
        "synced": True,
        "trialId": champ.get("trial_id") or champ.get("trialId"),
        "horizon": cfg.get("horizon"),
        "features": cfg.get("features") or [],
        "meanIc": metrics.get("mean_ic") or metrics.get("mean_rank_ic"),
        "quintileSpread": metrics.get("quintile_spread"),
        "objective": champ.get("objective"),
        "source": str(CHAMPION_SRC),
        "useForManifestBoost": bool(
            (metrics.get("quintile_spread") or 0) > 0 and
            (metrics.get("mean_ic") or metrics.get("mean_rank_ic") or 0) > 0.005
        ),
    }
    OVERLAY_PATH.write_text(json.dumps(overlay, indent=2), encoding="utf-8")
    TILT_PATH.write_text(json.dumps({
        "generatedAt": _now(),
        "globalTilt": 1.05 if overlay["useForManifestBoost"] else 1.0,
        "note": "Unified champion from nostradamus-live auto_search",
    }, indent=2), encoding="utf-8")
    print(f"[champion-sync] trial={overlay.get('trialId')} boost={overlay['useForManifestBoost']}", flush=True)
    return overlay


if __name__ == "__main__":
    run()
