"""Megamind chooses: improve mutable arena (v3+) in place vs spawn new arm — profit-focused."""
from __future__ import annotations

import json
from pathlib import Path

from .ledger import version_summary
from .operating import (
    active_mutable_versions,
    champion_version,
    challenger_version,
)
from .paths import (
    REPO,
    _load_experiment_raw,
    is_frozen,
    latest_mutable_version,
    list_versions,
    traders_path,
    version_for_recommendation,
)

MEGAMIND_GOAL = (
    "Find and build the most profitable research system for a future Robinhood AI agent: "
    "simulated books on real symbols and model signals (data/predictions_v3/live.csv), "
    "forward paper as the honest scoreboard, live trading only behind the readiness gate."
)


def _mutable_summaries(*, active_only: bool = True) -> dict[str, dict]:
    """Summaries for champion/challenger (or all mutables if active_only=False)."""
    if active_only:
        targets = active_mutable_versions()
    else:
        targets = [v for v in list_versions() if not is_frozen(v)]
    out = {}
    for v in targets:
        if traders_path(v).exists():
            out[v] = version_summary(v)
    return out


def _best_arm(summaries: dict[str, dict]) -> tuple[str | None, float]:
    best_v, best_m = None, -1e9
    for v, s in summaries.items():
        m = float(s.get("meanCumulativePct") or -1e9)
        if m > best_m:
            best_m, best_v = m, v
    return best_v, best_m


def _needs_new_feed(rec: dict, spec: dict) -> bool:
    area = (rec.get("area") or "").lower()
    if spec.get("feed_name") or spec.get("panel_path"):
        return True
    if area in ("data_pipelines", "arena_expansion"):
        return True
    return False


def _feed_already_used(feed_name: str | None) -> str | None:
    if not feed_name:
        return None
    slug = feed_name.replace("_", "-").lower()
    exp = _load_experiment_raw()
    for vid, meta in (exp.get("versions") or {}).items():
        if is_frozen(vid):
            continue
        path = (meta.get("panelPath") or "").lower()
        if feed_name.lower() in path or slug in path:
            return vid
    return None


def decide_arena_action(rec: dict, report: dict | None = None) -> dict:
    """
    Return Megamind's arena decision: update existing v3+ or spawn new.
    Never touches v1/v2.
    """
    spec = dict(rec.get("spawnSpec") or {})
    if (spec.get("action") or "").lower() in ("update", "spawn"):
        return {
            "action": spec["action"].lower(),
            "version": spec.get("version"),
            "reason": spec.get("reason") or "explicit in spawnSpec",
            "goal": MEGAMIND_GOAL,
        }

    report = report or {}
    compare = report.get("compare") or {}
    frozen_best = max(
        float((compare.get("v1Summary") or {}).get("meanCumulativePct") or 0),
        float((compare.get("v2Summary") or {}).get("meanCumulativePct") or 0),
    )
    mutable = _mutable_summaries(active_only=True)
    champ = champion_version()
    chall = challenger_version()
    rid = rec.get("id")
    linked = version_for_recommendation(rid) if rid else None
    latest = latest_mutable_version()

    # No champion yet — must spawn (becomes champion v3)
    if not champ and not mutable:
        return {
            "action": "spawn",
            "version": spec.get("version") or "v3",
            "reason": "No champion arena; spawn first mutable arm (v3) to chase profit beyond frozen v1/v2.",
            "goal": MEGAMIND_GOAL,
        }

    best_mut_v, best_mut_m = _best_arm(mutable)
    gap = frozen_best - best_mut_m if best_mut_v else 999.0
    n_active = len(mutable)

    # New feed / pipeline — challenger spawn only when no challenger on that feed
    if _needs_new_feed(rec, spec):
        existing = _feed_already_used(spec.get("feed_name"))
        if existing and existing in (champ, chall):
            return {
                "action": "update",
                "version": existing,
                "reason": f"Arm {existing} already uses this feed — improve in place.",
                "goal": MEGAMIND_GOAL,
            }
        if chall and not existing:
            return {
                "action": "update",
                "version": chall,
                "reason": (
                    f"Challenger {chall} already active — refine hypothesis in place "
                    "(operating rule: max one challenger pulsed)."
                ),
                "goal": MEGAMIND_GOAL,
            }
        if not chall and champ:
            return {
                "action": "spawn",
                "version": None,
                "reason": (
                    "New feed/hypothesis — spawn challenger arm (champion unchanged; "
                    "v1/v2 frozen)."
                ),
                "goal": MEGAMIND_GOAL,
            }

    # Linked arm — improve it unless it is clearly dead
    if linked and linked in mutable:
        linked_m = float(mutable[linked].get("meanCumulativePct") or 0)
        if linked_m >= frozen_best - 5.0 or gap < 2.0:
            return {
                "action": "update",
                "version": linked,
                "reason": f"Prior approval tied to {linked}; refine in place (mean cum {linked_m:.2f}%).",
                "goal": MEGAMIND_GOAL,
            }

    # Best mutable is competitive — evolve champion in place
    if best_mut_v and best_mut_m >= frozen_best - 1.5:
        target = champ or best_mut_v
        return {
            "action": "update",
            "version": target,
            "reason": (
                f"{target} within 1.5% of frozen leaders ({best_mut_m:.2f}% vs {frozen_best:.2f}%) — "
                "harvest/evolve champion; no new pool."
            ),
            "goal": MEGAMIND_GOAL,
        }

    # Underperforming — still update champion (cross-pool harvest), not sprawl
    if gap > 2.0:
        target = champ or best_mut_v or latest
        return {
            "action": "update",
            "version": target,
            "reason": (
                f"Champion {target} trails frozen {frozen_best:.2f}% by {gap:.1f}% — "
                "evolve from all sim pools instead of spawning duplicate arenas."
            ),
            "goal": MEGAMIND_GOAL,
        }

    target = champ or best_mut_v or latest
    return {
        "action": "update",
        "version": target,
        "reason": (
            f"Refine champion {target} (operating rule: update + harvest; "
            f"{n_active} active mutable pulse(s))."
        ),
        "goal": MEGAMIND_GOAL,
    }


def enrich_spawn_spec(rec: dict, report: dict | None = None) -> dict:
    """Attach Megamind's chosen action + reason to recommendation spawnSpec."""
    spec = dict(rec.get("spawnSpec") or {})
    if (spec.get("action") or "auto").lower() != "auto" and spec.get("reason"):
        return spec
    decision = decide_arena_action(rec, report)
    spec["action"] = decision["action"]
    if decision.get("version"):
        spec["version"] = decision["version"]
    spec["reason"] = decision["reason"]
    spec["megamindGoal"] = decision["goal"]
    return spec
