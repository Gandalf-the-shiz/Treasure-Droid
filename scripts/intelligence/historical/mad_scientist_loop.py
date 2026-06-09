"""Mad Scientist 24/7 loop — endless historical experiments → champion promotion.

Rotates experiment profiles, spawns genomes on the historical panel, logs every
run, promotes shadow fleet agents when holdout Sharpe clears the bar.

Usage:
  python scripts/intelligence/historical/mad_scientist_loop.py --once
  python scripts/intelligence/historical/mad_scientist_loop.py --cycles 0   # infinite
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
STATE_PATH = REPO / "data" / "intelligence" / "historical" / "loop_state.json"
LOG_PATH = REPO / "data" / "intelligence" / "historical" / "experiment_log.jsonl"
CONFIG_PATH = REPO / "config" / "mad_scientist_lab.json"
PANEL_META = REPO / "data" / "intelligence" / "historical" / "panel_meta.json"

sys.path.insert(0, str(REPO / "scripts"))

DEFAULT_PROFILES = [
    {"name": "alpha_neutral_wide", "genomes": 400, "signal_bias": "alpha", "promote": 3},
    {"name": "edge_hunter", "genomes": 300, "signal_bias": "edge", "promote": 2},
    {"name": "deep_search", "genomes": 600, "signal_bias": "mixed", "promote": 4},
    {"name": "tight_holdout", "genomes": 350, "selection_frac": 0.5, "promote": 2},
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"cycle": 0, "profile_idx": 0, "seed": 42, "champions": []}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updatedAt"] = _now()
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _append_log(entry: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _panel_stale(max_age_days: int = 7) -> bool:
    if not PANEL_META.exists():
        return True
    try:
        meta = json.loads(PANEL_META.read_text(encoding="utf-8"))
        gen = meta.get("generatedAt", "")
        if not gen:
            return True
        ts = datetime.fromisoformat(gen.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
        return age >= max_age_days
    except Exception:
        return True


def _run_profile(profile: dict, seed: int) -> dict:
    """Execute one experiment profile on the historical panel."""
    from intelligence.historical.walkforward_lab import run as lab_run

    genomes = int(profile.get("genomes") or 300)
    promote = int(profile.get("promote") or 2)
    rebuild = profile.get("rebuild_panel", False)

    # Patch spawn seed via env for this cycle (walkforward uses seed=42 default).
    import intelligence.historical.walkforward_lab as lab_mod
    orig_spawn = lab_mod._spawn_genomes

    def _seeded_spawn(n: int, seed_: int = seed):
        return orig_spawn(n, seed=seed_)

    lab_mod._spawn_genomes = _seeded_spawn
    try:
        doc = lab_run(genomes=genomes, promote=promote, rebuild_panel=rebuild or _panel_stale())
    finally:
        lab_mod._spawn_genomes = orig_spawn

    return doc


def one_cycle(state: dict | None = None) -> dict:
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    profiles = cfg.get("experiment_profiles") or DEFAULT_PROFILES
    min_holdout_sharpe = float(cfg.get("min_promote_holdout_sharpe") or 0.5)

    state = state or _load_state()
    idx = int(state.get("profile_idx") or 0) % len(profiles)
    profile = profiles[idx]
    seed = int(state.get("seed") or 42) + int(state.get("cycle") or 0)

    print(f"[mad-scientist-loop] cycle={state.get('cycle')} profile={profile.get('name')} seed={seed}", flush=True)
    doc = _run_profile(profile, seed)

    best = (doc.get("leaderboard") or [{}])[0] if doc.get("ok") else {}
    survivors = doc.get("survivors") or []
    promoted = [s for s in survivors if (s.get("holdout") or {}).get("sharpe", 0) >= min_holdout_sharpe]

    entry = {
        "ts": _now(),
        "cycle": state.get("cycle"),
        "profile": profile.get("name"),
        "seed": seed,
        "nGenomes": doc.get("nGenomes"),
        "nScored": doc.get("nScored"),
        "bestHoldoutSharpe": best.get("holdSharpe"),
        "bestHoldoutReturnPct": best.get("holdReturnPct"),
        "nSurvivors": len(survivors),
        "nPromoted": len(promoted),
        "verdict": doc.get("verdict"),
    }
    _append_log(entry)

    champions = state.get("champions") or []
    if best.get("holdSharpe") is not None:
        champions.append({
            "ts": _now(),
            "id": best.get("id"),
            "family": best.get("family"),
            "holdSharpe": best.get("holdSharpe"),
            "holdReturnPct": best.get("holdReturnPct"),
            "profile": profile.get("name"),
        })
        champions = sorted(champions, key=lambda c: c.get("holdSharpe") or -9, reverse=True)[:25]

    state["cycle"] = int(state.get("cycle") or 0) + 1
    state["profile_idx"] = (idx + 1) % len(profiles)
    state["seed"] = seed
    state["lastProfile"] = profile.get("name")
    state["lastResult"] = entry
    state["champions"] = champions
    state["status"] = "running"
    _save_state(state)

    print(
        f"[mad-scientist-loop] done profile={profile.get('name')} "
        f"best_holdout_sharpe={best.get('holdSharpe')} survivors={len(survivors)}",
        flush=True,
    )
    return {"state": state, "result": doc, "log": entry}


def run_loop(*, cycles: int = 0, sleep_minutes: int = 180) -> None:
    """cycles=0 means run forever."""
    n = 0
    while cycles == 0 or n < cycles:
        try:
            one_cycle()
        except Exception as exc:
            print(f"[mad-scientist-loop] cycle error: {exc}", flush=True)
            _append_log({"ts": _now(), "error": str(exc)[:500]})
        n += 1
        if cycles == 0 or n < cycles:
            wait = max(60, sleep_minutes * 60)
            print(f"[mad-scientist-loop] sleeping {sleep_minutes}m", flush=True)
            time.sleep(wait)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Mad Scientist 24/7 historical experiment loop")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--cycles", type=int, default=0, help="0=infinite")
    ap.add_argument("--sleep-minutes", type=int, default=180)
    args = ap.parse_args()
    if args.once:
        one_cycle()
    else:
        run_loop(cycles=args.cycles, sleep_minutes=args.sleep_minutes)
