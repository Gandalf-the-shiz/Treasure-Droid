"""Cross-pool genome harvest + champion evolution (operating model)."""
from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path

from .engine import STRATEGY_FAMILIES, spawn_traders
from .ledger import ranked_traders
from .operating import CHAMPION_POPULATION, champion_version, is_archived
from .paths import (
    MASTER_SEEDS,
    _now,
    is_frozen,
    list_versions,
    traders_path,
)

REPO = Path(__file__).resolve().parents[3]
HARVEST_PATH = REPO / "data" / "trader_arena" / "harvest_latest.json"

GENOME_KEYS = (
    "family", "min_proba", "min_pred_ret", "short_enabled", "short_frac",
    "top_k", "kelly", "crowd_w", "insider_w", "alt_scale", "contrarian",
    "selection_mode",
)


def _genome_from_entry(entry: dict) -> dict:
    g = dict(entry.get("genome") or {})
    g.setdefault("family", entry.get("family"))
    return {k: g[k] for k in GENOME_KEYS if k in g and g[k] is not None}


def harvest_genomes(*, top_frac: float = 0.10, min_per_pool: int = 3) -> dict:
    """Collect elite genomes from every arena ledger (including archived pools)."""
    parents: list[dict] = []
    by_pool: dict[str, int] = {}

    for version in list_versions():
        rows = ranked_traders(version)
        if not rows:
            continue
        n_take = max(min_per_pool, int(len(rows) * top_frac))
        n_take = min(n_take, len(rows))
        taken = 0
        for row in rows[:n_take]:
            g = _genome_from_entry(row)
            if not g.get("family"):
                continue
            parents.append({
                **g,
                "_sourceVersion": version,
                "_sourceTraderId": row.get("traderId"),
                "_cumulativeReturnPct": float(row.get("cumulativeReturnPct") or 0),
            })
            taken += 1
        by_pool[version] = taken

        # Per-family champion in each pool
        families: dict[str, dict] = {}
        for row in rows:
            fam = row.get("family") or (row.get("genome") or {}).get("family")
            if not fam:
                continue
            cum = float(row.get("cumulativeReturnPct") or 0)
            if fam not in families or cum > float(families[fam].get("cumulativeReturnPct") or 0):
                families[fam] = row
        for fam, row in families.items():
            g = _genome_from_entry(row)
            if g:
                parents.append({
                    **g,
                    "_sourceVersion": version,
                    "_sourceTraderId": row.get("traderId"),
                    "_familyChampion": fam,
                    "_cumulativeReturnPct": float(row.get("cumulativeReturnPct") or 0),
                })

    # Dedupe by coarse genome signature
    seen: set[str] = set()
    unique: list[dict] = []
    for p in sorted(parents, key=lambda x: -float(x.get("_cumulativeReturnPct") or 0)):
        sig = json.dumps({k: p.get(k) for k in GENOME_KEYS}, sort_keys=True)
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(p)

    doc = {
        "generatedAt": _now(),
        "nParents": len(unique),
        "byPool": by_pool,
        "includesArchived": any(is_archived(v) for v in by_pool),
        "parents": unique[:200],
    }
    HARVEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    HARVEST_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def _mutate(genome: dict, rng: random.Random, selection_mode: str) -> dict:
    g = deepcopy(genome)
    g["selection_mode"] = selection_mode
    if rng.random() < 0.35:
        g["min_proba"] = round(max(0.50, min(0.72, float(g.get("min_proba") or 0.58) + rng.uniform(-0.04, 0.04))), 3)
    if rng.random() < 0.35:
        g["min_pred_ret"] = round(max(0.003, min(0.05, float(g.get("min_pred_ret") or 0.015) + rng.uniform(-0.006, 0.006))), 4)
    if rng.random() < 0.3:
        g["top_k"] = max(5, min(25, int(g.get("top_k") or 10) + rng.randint(-3, 3)))
    if rng.random() < 0.3:
        g["kelly"] = round(max(0.2, min(0.85, float(g.get("kelly") or 0.5) + rng.uniform(-0.12, 0.12))), 3)
    if rng.random() < 0.2:
        g["alt_scale"] = round(max(0.55, min(1.45, float(g.get("alt_scale") or 1.0) + rng.uniform(-0.15, 0.15))), 3)
    if rng.random() < 0.15:
        g["family"] = rng.choice(STRATEGY_FAMILIES)
    return g


def _crossover(a: dict, b: dict, rng: random.Random, selection_mode: str) -> dict:
    child = {}
    for k in GENOME_KEYS:
        child[k] = a.get(k) if rng.random() < 0.5 else b.get(k)
    child["selection_mode"] = selection_mode
    return _mutate(child, rng, selection_mode)


def evolve_champion(
    version: str | None = None,
    *,
    population: int = CHAMPION_POPULATION,
    elite_keep_frac: float = 0.50,
    replace_bottom_frac: float = 0.25,
) -> dict:
    """
    Replace bottom quartile of champion genomes with children from cross-pool harvest.
    Preserves top performers; does not respawn entire population.
    """
    vid = version or champion_version()
    if not vid:
        raise ValueError("No champion arena to evolve")
    if is_frozen(vid):
        raise ValueError(f"Cannot evolve frozen arena {vid}")

    harvest = harvest_genomes()
    parents = harvest.get("parents") or []
    if len(parents) < 2:
        return {"evolved": False, "reason": "insufficient harvest parents", "version": vid}

    if not traders_path(vid).exists():
        spawn_traders(vid, population)
        return {"evolved": True, "version": vid, "spawnedFresh": True, "nTraders": population}

    doc = json.loads(traders_path(vid).read_text(encoding="utf-8"))
    traders = list(doc.get("traders") or [])
    ranked = {int(r["traderId"]): r for r in ranked_traders(vid)}
    traders.sort(
        key=lambda t: float((ranked.get(int(t["trader_id"])) or {}).get("cumulativeReturnPct") or 0),
        reverse=True,
    )

    exp_meta = (_load_meta(vid))
    selection_mode = exp_meta.get("selectionMode") or "rank_v2"
    master = MASTER_SEEDS.get(vid, 20260700)
    n_keep = max(1, int(len(traders) * elite_keep_frac))
    n_replace = max(1, int(len(traders) * replace_bottom_frac))
    elites = traders[:n_keep]
    tail_ids = {int(t["trader_id"]) for t in traders[-n_replace:]}

    rng = random.Random(int(_now()[:10].replace("-", "")) + len(parents))
    strip_parent = lambda p: {k: v for k, v in p.items() if not str(k).startswith("_")}

    new_tail = []
    pid = max(int(t["trader_id"]) for t in traders) + 1
    while len(new_tail) < n_replace:
        pa = strip_parent(rng.choice(parents))
        pb = strip_parent(rng.choice(parents))
        child = _crossover(pa, pb, rng, selection_mode)
        seed = master + pid
        tr = random.Random(seed)
        family = child.get("family") or tr.choice(STRATEGY_FAMILIES)
        short_on = family in {"short_bias", "long_short_neutral"} or tr.random() < 0.4
        new_tail.append({
            "trader_id": pid,
            "seed": seed,
            "family": family,
            "arena_version": vid,
            "selection_mode": selection_mode,
            "min_proba": child.get("min_proba", round(tr.uniform(0.52, 0.68), 3)),
            "min_pred_ret": child.get("min_pred_ret", round(tr.uniform(0.005, 0.02), 4)),
            "short_enabled": short_on,
            "short_frac": round(tr.uniform(0.1, 0.4) if short_on else 0.0, 3),
            "top_k": child.get("top_k", tr.randint(5, 20)),
            "kelly": child.get("kelly", round(tr.uniform(0.25, 0.8), 3)),
            "crowd_w": round(tr.uniform(0, 0.35), 3),
            "insider_w": round(tr.uniform(0, 0.35), 3),
            "alt_scale": child.get("alt_scale", round(tr.uniform(0.75, 1.25), 3)),
            "contrarian": bool(child.get("contrarian") or family == "contrarian"),
            "evolvedFrom": "cross_pool_harvest",
        })
        pid += 1

    middle = [t for t in traders[n_keep:] if int(t["trader_id"]) not in tail_ids]
    merged = elites + middle + new_tail
    while len(merged) < population:
        pa = strip_parent(rng.choice(parents))
        pb = strip_parent(rng.choice(parents))
        child = _crossover(pa, pb, rng, selection_mode)
        seed = master + pid
        tr = random.Random(seed)
        family = child.get("family") or tr.choice(STRATEGY_FAMILIES)
        short_on = family in {"short_bias", "long_short_neutral"} or tr.random() < 0.4
        merged.append({
            "trader_id": pid,
            "seed": seed,
            "family": family,
            "arena_version": vid,
            "selection_mode": selection_mode,
            "min_proba": child.get("min_proba", round(tr.uniform(0.52, 0.68), 3)),
            "min_pred_ret": child.get("min_pred_ret", round(tr.uniform(0.005, 0.02), 4)),
            "short_enabled": short_on,
            "short_frac": round(tr.uniform(0.1, 0.4) if short_on else 0.0, 3),
            "top_k": child.get("top_k", tr.randint(5, 20)),
            "kelly": child.get("kelly", round(tr.uniform(0.25, 0.8), 3)),
            "crowd_w": round(tr.uniform(0, 0.35), 3),
            "insider_w": round(tr.uniform(0, 0.35), 3),
            "alt_scale": child.get("alt_scale", round(tr.uniform(0.75, 1.25), 3)),
            "contrarian": bool(child.get("contrarian") or family == "contrarian"),
            "evolvedFrom": "cross_pool_harvest",
        })
        pid += 1
    if len(merged) > population:
        merged = merged[:population]

    doc["traders"] = merged[:population]
    doc["count"] = len(doc["traders"])
    doc["evolvedAt"] = _now()
    doc["harvestParents"] = len(parents)
    traders_path(vid).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return {
        "evolved": True,
        "version": vid,
        "nTraders": len(doc["traders"]),
        "nReplaced": n_replace,
        "nHarvestParents": len(parents),
        "harvestPath": str(HARVEST_PATH.relative_to(REPO)),
    }


def _load_meta(version: str) -> dict:
    from .paths import _load_experiment_raw
    return (_load_experiment_raw().get("versions") or {}).get(version) or {}


def run_harvest_evolve_cycle() -> dict:
    from .operating import ensure_operating_model

    ensure_operating_model()
    h = harvest_genomes()
    e: dict = {}
    champ = champion_version()
    if champ:
        try:
            e = evolve_champion(champ)
        except ValueError as exc:
            e = {"evolved": False, "error": str(exc)}
    return {"harvest": h, "evolve": e, "champion": champ}
