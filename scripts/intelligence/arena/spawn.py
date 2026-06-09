"""Spawn new Investor Arena versions (v3+) without touching frozen v1/v2."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .engine import run_pulse, spawn_traders
from .paths import (
    ARENA_ROOT,
    PANEL_PATH,
    REPO,
    _now,
    ensure_experiment,
    list_versions,
    next_version_id,
    register_version,
    traders_path,
)
from .policy import assert_mutable

_FEED_ROOT = REPO / "data" / "arena_feeds"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "feed").lower()).strip("-")[:40]


def _rel_repo(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def spawn_new_arena(
    *,
    version: str | None = None,
    label: str = "",
    selection_mode: str = "rank_v2",
    panel_path: str | None = None,
    feed_name: str | None = None,
    n_traders: int = 100,
    source_recommendation: str | None = None,
) -> dict:
    """Register and spawn a new arena version. Raises if version is frozen or exists."""
    vid = version or next_version_id()
    assert_mutable(vid, "spawn over")
    if vid in list_versions() and traders_path(vid).exists():
        raise ValueError(f"Arena {vid} already exists — pick another version or archive first")

    exp = ensure_experiment()
    if feed_name and not panel_path:
        panel_abs = _FEED_ROOT / f"{_slug(feed_name)}.csv"
        if not panel_abs.exists() and PANEL_PATH.exists():
            _FEED_ROOT.mkdir(parents=True, exist_ok=True)
            shutil.copy2(PANEL_PATH, panel_abs)
        panel_path = _rel_repo(panel_abs) if panel_abs.exists() else None

    meta = {
        "startedAt": _now(),
        "nTraders": n_traders,
        "label": label or f"Investor Arena {vid} ({selection_mode})",
        "selectionMode": selection_mode,
        "panelPath": panel_path or _rel_repo(PANEL_PATH),
        "megamindSpawned": True,
        "sourceRecommendation": source_recommendation,
        "frozen": False,
    }
    register_version(vid, meta)
    spawn_traders(vid, n_traders, selection_mode=selection_mode)
    arena = run_pulse(vid, n_traders)
    return {"version": vid, "meta": meta, "summary": arena.get("summary"), "spawned": True}


def spawn_from_recommendation(rec: dict) -> dict | None:
    """Backward-compatible alias — prefer apply_arena_from_recommendation."""
    from .mutable import apply_arena_from_recommendation

    return apply_arena_from_recommendation(rec)
