"""Fleet registry — the crew of forward-paper agents.

Seeded from the live systems: the market-neutral alpha book, the investor v3
allocator, and the top champion arena genomes. Treasure Droid (captain) grows
and prunes this crew over time based on forward performance.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO / "data" / "fleet" / "registry.json"
ARENA_DIR = REPO / "data" / "trader_arena"

# Robot-pirate crew names for genome agents.
GENOME_NAMES = ["Goldtooth", "Sparks", "Rusty-Pete", "Cutlass", "Doubloon", "Scrapjack"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return default


def _champion_version() -> str:
    exp = _load(ARENA_DIR / "experiment.json", {})
    om = exp.get("operatingModel") or {}
    champ = om.get("champion")
    if champ and (ARENA_DIR / champ).exists():
        return champ
    for v in ("v3", "v2", "v1"):
        if (ARENA_DIR / v / "traders.json").exists():
            return v
    return "v3"


def _top_genomes(version: str, n: int = 3) -> list[dict]:
    lb = _load(ARENA_DIR / version / "leaderboard.json", {})
    traders_doc = _load(ARENA_DIR / version / "traders.json", {})
    genomes = {int(t["trader_id"]): t for t in (traders_doc.get("traders") or [])}
    ranked = lb.get("top10") or lb.get("ranked") or []
    out = []
    for i, row in enumerate(ranked[:n]):
        tid = row.get("traderId", row.get("trader_id"))
        # Leaderboard rows carry the genome inline (survives evolution id drift).
        g = row.get("genome") or (genomes.get(int(tid)) if tid is not None else None)
        if not g:
            continue
        out.append({
            "trader_id": int(tid) if tid is not None else i,
            "family": g.get("family"),
            "min_proba": g.get("min_proba", 0.58),
            "min_pred_ret": g.get("min_pred_ret", 0.01),
            "top_k": g.get("top_k", 8),
            "kelly": g.get("kelly", 0.5),
            "short_enabled": bool(g.get("short_enabled")),
            "short_frac": g.get("short_frac", 0.0),
        })
    return out


def _seed() -> dict:
    agents = [
        {"id": "navigator", "name": "The Navigator", "kind": "alpha_blended",
         "status": "shadow", "capital": 100000.0,
         "blurb": "Market-neutral long/short from the blended, neutralized alpha.",
         "params": {}, "createdAt": _now()},
        {"id": "quartermaster", "name": "The Quartermaster", "kind": "investor_v3",
         "status": "shadow", "capital": 100000.0,
         "blurb": "Long-only conviction book, half-Kelly by win probability.",
         "params": {"top_k": 8, "min_proba": 0.55, "gross": 0.9}, "createdAt": _now()},
    ]
    champ = _champion_version()
    for i, g in enumerate(_top_genomes(champ, 3)):
        agents.append({
            "id": f"genome_{champ}_{g['trader_id']}",
            "name": GENOME_NAMES[i % len(GENOME_NAMES)],
            "kind": "genome", "status": "shadow", "capital": 100000.0,
            "blurb": f"Arena {champ} genome #{g['trader_id']} ({g.get('family')}) walking forward.",
            "params": g, "createdAt": _now(),
        })
    return {"agents": agents, "updatedAt": _now(), "championVersion": champ}


def load_registry(reseed: bool = False) -> dict:
    if REGISTRY_PATH.exists() and not reseed:
        doc = _load(REGISTRY_PATH, None)
        if doc and doc.get("agents"):
            return doc
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc = _seed()
    REGISTRY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def save_registry(doc: dict) -> None:
    doc["updatedAt"] = _now()
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--reseed", action="store_true")
    args = ap.parse_args()
    print(json.dumps(load_registry(reseed=args.reseed), indent=2))
