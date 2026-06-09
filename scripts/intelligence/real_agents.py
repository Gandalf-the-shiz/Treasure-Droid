"""Real ML agent registry — distill sim+harness into ≤5 forward-facing agents."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO / "data" / "intelligence" / "real_agents" / "registry.json"
MAX_POLICY_AGENTS = 4


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _predictor_slot() -> dict:
    live = REPO / "data" / "predictions_v3" / "live.csv"
    meta_path = REPO / "models" / "v3" / "predictor" / "meta.joblib"
    slot = {
        "id": "predictor_v3",
        "role": "predictor",
        "status": "active",
        "source": "generate_live_predictions.py",
        "panelPath": "data/predictions_v3/live.csv",
        "panelReady": live.exists(),
    }
    if meta_path.exists():
        slot["modelDir"] = "models/v3/predictor"
    triggers = REPO / "data" / "learning" / "retrain_triggers.json"
    if triggers.exists():
        try:
            t = json.loads(triggers.read_text(encoding="utf-8-sig"))
            slot["retrainTriggers"] = {
                "predictor": bool(t.get("triggerPredictorRetrain")),
                "investor": bool(t.get("triggerInvestorRetrain")),
            }
        except (OSError, json.JSONDecodeError):
            pass
    return slot


def _policy_from_genome(entry: dict, rank: int) -> dict:
    g = entry.get("genome") or {}
    tid = entry.get("traderId")
    return {
        "id": f"policy_champion_{tid}",
        "role": "execution_policy",
        "status": "candidate",
        "rank": rank,
        "distilledFrom": "arena_champion",
        "traderId": tid,
        "family": g.get("family") or entry.get("family"),
        "genome": {k: g[k] for k in (
            "min_proba", "min_pred_ret", "short_enabled", "short_frac",
            "top_k", "kelly", "alt_scale", "selection_mode", "contrarian",
        ) if k in g},
        "simCumulativeReturnPct": float(entry.get("cumulativeReturnPct") or 0),
        "note": "Sim performance — forward paper required before promotion to active.",
    }


def sync_registry() -> dict:
    """Build registry: 1 predictor + top policy slots from champion ledger."""
    from intelligence.arena.operating import champion_version, ensure_operating_model
    from intelligence.arena.ledger import ranked_traders

    ensure_operating_model()
    agents: list[dict] = [_predictor_slot()]

    champ = champion_version()
    if champ:
        rows = ranked_traders(champ)[:MAX_POLICY_AGENTS]
        for i, row in enumerate(rows, 1):
            agents.append(_policy_from_genome(row, i))

    # Preserve manual promotions
    prev = {}
    if REGISTRY_PATH.exists():
        try:
            old = json.loads(REGISTRY_PATH.read_text(encoding="utf-8-sig"))
            for a in old.get("agents") or []:
                if a.get("status") == "active" and a.get("role") == "execution_policy":
                    prev[a["id"]] = a
        except (OSError, json.JSONDecodeError):
            pass
    for a in agents:
        if a["id"] in prev and prev[a["id"]].get("forwardApproved"):
            a["status"] = "active"
            a["forwardApproved"] = True

    doc = {
        "generatedAt": _now(),
        "maxAgents": 1 + MAX_POLICY_AGENTS,
        "championArena": champ,
        "agents": agents,
        "policy": (
            "One shared predictor; up to four execution policies distilled from champion sim. "
            "Live trading only behind readiness gate."
        ),
    }
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        f"[real-agents] {len(agents)} slots (1 predictor + {len(agents) - 1} policies) champion={champ}",
        flush=True,
    )
    return doc


def run_operating_cycle(*, evolve: bool = True) -> dict:
    from intelligence.arena.harvest import harvest_genomes, evolve_champion
    from intelligence.arena.operating import champion_version, ensure_operating_model

    ensure_operating_model()
    out = {"operating": ensure_operating_model()}
    out["harvest"] = harvest_genomes()
    out["evolve"] = {}
    if evolve:
        c = champion_version()
        if c:
            try:
                out["evolve"] = evolve_champion(c)
            except ValueError as exc:
                out["evolve"] = {"evolved": False, "error": str(exc)}
    out["realAgents"] = sync_registry()
    return out
