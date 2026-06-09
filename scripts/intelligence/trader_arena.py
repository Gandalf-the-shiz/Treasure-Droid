"""Trader arena CLI — Investor Arena v1 + v2 (200 agents total).

Usage:
  python scripts/intelligence/trader_arena.py --pulse              # both versions
  python scripts/intelligence/trader_arena.py --pulse --version v1
  python scripts/intelligence/trader_arena.py --respawn --version v2
  python scripts/intelligence/trader_arena.py --migrate
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

from intelligence.arena import (  # noqa: E402
    ensure_both_versions,
    migrate_legacy,
    run_active_pulses,
    run_all_pulses,
    run_pulse,
    spawn_traders,
)
from intelligence.arena.paths import VERSIONS, is_frozen, list_versions  # noqa: E402
from intelligence.arena.spawn import spawn_new_arena  # noqa: E402
from intelligence.real_agents import run_operating_cycle  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--traders", type=int, default=100)
    ap.add_argument("--pulse", action="store_true")
    ap.add_argument("--respawn", action="store_true")
    ap.add_argument("--migrate", action="store_true", help="move legacy files to v1/")
    ap.add_argument(
        "--version",
        default="active",
        help="active (v1+v2+champion+challenger), all versions, or v1, v2, v3, …",
    )
    ap.add_argument("--consolidate", action="store_true", help="Archive duplicate mutables; set champion v3")
    ap.add_argument("--harvest-evolve", action="store_true", help="Cross-pool harvest + evolve champion")
    ap.add_argument("--spawn-new", action="store_true", help="spawn new arena (v3+) from --spec JSON file")
    ap.add_argument("--spec", metavar="PATH", help="JSON spec for --spawn-new")
    args = ap.parse_args()

    if args.consolidate:
        from intelligence.arena.operating import ensure_operating_model
        print(json.dumps(ensure_operating_model(force=True), indent=2), flush=True)
        return 0

    if args.harvest_evolve:
        print(json.dumps(run_operating_cycle(evolve=True), indent=2)[:3000], flush=True)
        return 0

    if args.migrate:
        migrate_legacy()
        print("[arena] migrated legacy data to v1/", flush=True)

    migrate_legacy()
    ensure_both_versions(args.traders)
    from intelligence.arena.operating import ensure_operating_model
    ensure_operating_model()

    if args.spawn_new:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8-sig")) if args.spec else {}
        out = spawn_new_arena(n_traders=args.traders, **spec)
        print(json.dumps(out, indent=2)[:2000], flush=True)
        return 0

    if args.version == "all":
        versions = list_versions()
    elif args.version == "active":
        from intelligence.arena.operating import pulse_versions
        versions = pulse_versions()
    else:
        versions = [args.version]

    if args.respawn:
        for v in versions:
            if is_frozen(v):
                print(f"[arena] skip respawn — {v} is frozen (Megamind policy)", flush=True)
                continue
            spawn_traders(v, args.traders)
            print(f"[arena] respawned {args.traders} genomes for {v}", flush=True)

    if args.pulse:
        if args.version in ("all", "active"):
            pulse_fn = run_active_pulses if args.version == "active" else run_all_pulses
            doc = pulse_fn(args.traders)
            keys = doc.get("pulseVersions") or ["v1", "v2"]
            print(json.dumps({k: (doc.get(k) or {}).get("summary") for k in keys if k in doc}, indent=2)[:1500], flush=True)
        else:
            run_pulse(args.version, args.traders)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
