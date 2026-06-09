"""Update mutable arenas (v3+) in place; spawn only when needed."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .engine import run_pulse
from .paths import (
    PANEL_PATH,
    REPO,
    _load_experiment_raw,
    _now,
    is_frozen,
    latest_mutable_version,
    list_versions,
    next_version_id,
    register_version,
    traders_path,
    update_version_meta,
    version_for_recommendation,
)
from .policy import assert_mutable
from .operating import (
    archive_version,
    champion_version,
    challenger_version,
    set_challenger,
    set_champion,
)
from .spawn import _rel_repo, _slug, spawn_new_arena

_FEED_ROOT = REPO / "data" / "arena_feeds"


def update_mutable_arena(
    version: str,
    *,
    label: str | None = None,
    selection_mode: str | None = None,
    panel_path: str | None = None,
    feed_name: str | None = None,
    n_traders: int = 100,
    source_recommendation: str | None = None,
) -> dict:
    """Pulse and refresh metadata for v3+ without respawning genomes."""
    assert_mutable(version, "update")
    if not traders_path(version).exists():
        raise ValueError(f"Arena {version} has no traders — use spawn, not update")

    if feed_name and not panel_path:
        panel_abs = _FEED_ROOT / f"{_slug(feed_name)}.csv"
        if PANEL_PATH.exists():
            _FEED_ROOT.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PANEL_PATH, panel_abs)
        if panel_abs.exists():
            panel_path = _rel_repo(panel_abs)

    patch = {"lastUpdatedAt": _now(), "lastPulseAt": _now()}
    if label:
        patch["label"] = label
    if selection_mode:
        patch["selectionMode"] = selection_mode
    if panel_path:
        patch["panelPath"] = panel_path
    if source_recommendation:
        patch["sourceRecommendation"] = source_recommendation
    meta = update_version_meta(version, patch)
    arena = run_pulse(version, n_traders)
    return {
        "version": version,
        "meta": meta,
        "summary": arena.get("summary"),
        "updated": True,
        "spawned": False,
    }


def apply_arena_from_recommendation(rec: dict, report: dict | None = None) -> dict | None:
    """Megamind applies arena change: update v3+ in place or spawn (never v1/v2)."""
    area = (rec.get("area") or "").lower()
    if area not in ("arena_expansion", "arena_spawn", "concentration_risk", "data_pipelines"):
        return None

    from .decision import decide_arena_action, enrich_spawn_spec

    report_path = REPO / "data" / "intelligence" / "megamind" / "latest_report.json"
    if report is None and report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            report = {}

    spec = enrich_spawn_spec(rec, report)
    decision = decide_arena_action({**rec, "spawnSpec": spec}, report)
    action = decision["action"]
    spec.setdefault("version", decision.get("version"))
    spec["reason"] = decision.get("reason", "")

    if area == "concentration_risk" and not spec:
        spec = {
            "label": "Megamind experimental — liquidity-aware rank panel",
            "selection_mode": "rank_v2",
            "feed_name": "arena_v3_liquidity_panel",
            "action": "auto",
        }
    if area == "data_pipelines" and not spec.get("feed_name"):
        return None
    if not spec and area not in ("arena_expansion", "arena_spawn"):
        return None

    rid = rec.get("id")
    linked = version_for_recommendation(rid) if rid else None
    latest = latest_mutable_version()

    if action == "update":
        vid = spec.get("version") or linked or latest
        if not vid:
            action = "spawn"
        else:
            try:
                out = update_mutable_arena(
                    vid,
                    label=spec.get("label"),
                    selection_mode=spec.get("selection_mode"),
                    panel_path=spec.get("panel_path"),
                    feed_name=spec.get("feed_name"),
                    n_traders=int(spec.get("n_traders") or 112),
                    source_recommendation=rid,
                )
                out["megamindDecision"] = decision
                return out
            except ValueError as exc:
                return {"error": str(exc), "updated": False, "spawned": False, "megamindDecision": decision}

    if action == "spawn":
        vid = spec.get("version")
        if vid and is_frozen(vid):
            return {"error": f"cannot spawn over frozen {vid}", "spawned": False}
        if vid and traders_path(vid).exists():
            out = update_mutable_arena(
                vid,
                label=spec.get("label"),
                selection_mode=spec.get("selection_mode"),
                panel_path=spec.get("panel_path"),
                feed_name=spec.get("feed_name"),
                n_traders=int(spec.get("n_traders") or 112),
                source_recommendation=rid,
            )
            out["megamindDecision"] = {**decision, "action": "update", "reason": spec.get("reason", "")}
            return out

        champ = champion_version()
        needs_feed = bool(spec.get("feed_name") or spec.get("panel_path"))
        # No new feed: never fork — update champion
        if champ and not needs_feed:
            out = update_mutable_arena(
                champ,
                label=spec.get("label"),
                selection_mode=spec.get("selection_mode"),
                panel_path=spec.get("panel_path"),
                feed_name=spec.get("feed_name"),
                n_traders=int(spec.get("n_traders") or 112),
                source_recommendation=rid,
            )
            out["megamindDecision"] = {**decision, "action": "update", "reason": "Routed to champion update (no new feed)."}
            return out

        old_chall = challenger_version()
        if old_chall and needs_feed:
            archive_version(old_chall, reason="Replaced by new Megamind challenger hypothesis")

        try:
            out = spawn_new_arena(
                version=vid or next_version_id(),
                label=spec.get("label") or rec.get("action", "")[:120],
                selection_mode=spec.get("selection_mode") or "rank_v2",
                panel_path=spec.get("panel_path"),
                feed_name=spec.get("feed_name"),
                n_traders=int(spec.get("n_traders") or 112),
                source_recommendation=rid,
            )
            out["updated"] = False
            new_vid = out.get("version")
            if new_vid:
                if not champ:
                    set_champion(new_vid)
                    out["role"] = "champion"
                elif needs_feed:
                    set_challenger(new_vid)
                    out["role"] = "challenger"
                else:
                    set_champion(new_vid)
                    out["role"] = "champion"
            out["megamindDecision"] = decision
            return out
        except ValueError as exc:
            return {"error": str(exc), "spawned": False, "megamindDecision": decision}

    return None
