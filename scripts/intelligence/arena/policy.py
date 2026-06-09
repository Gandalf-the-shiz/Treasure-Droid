"""Investor Arena immutability rules for Megamind and tooling."""
from __future__ import annotations

FROZEN_VERSIONS = frozenset({"v1", "v2"})

ARENA_POLICY_MARKDOWN = """
## Investor Arena rules (Megamind — mandatory)

### v1 / v2 (frozen baselines)
- **Never** delete, respawn, or rewrite genomes.
- **Do** daily pulse (returns update; ledgers saved and snapshotted under `data/trader_arena/snapshots/`).

### Operating model (v3+)
- **Champion** (default v3): one evolving population (~112 traders). Cross-pool **harvest** from all ledgers (incl. archived forks); **evolve** replaces bottom quartile.
- **Challenger** (optional): at most **one** extra mutable arm when testing a **new feed/hypothesis**; old challenger archived when replaced.
- **Pulse** only `active` versions: v1, v2, champion, challenger (`--version active`). Archived pools (v4–v6) are harvest-only.
- **Prefer update** champion; **spawn** challenger only for new feeds — never duplicate pools for the same panel.
- **Real ML agents:** `data/intelligence/real_agents/registry.json` — 1 predictor + ≤4 policy slots from champion top sim.

- Do **not** run `--respawn` on v1/v2.
"""


def is_frozen(version: str) -> bool:
    return version in FROZEN_VERSIONS


def assert_mutable(version: str, action: str = "modify") -> None:
    if is_frozen(version):
        raise ValueError(
            f"Investor Arena {version} is frozen — Megamind cannot {action} it. "
            "Spawn a new version (v3+) instead."
        )
