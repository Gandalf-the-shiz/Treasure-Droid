"""Paths for Investor Arena v1 / v2 experiment."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ARENA_ROOT = REPO / "data" / "trader_arena"
EXPERIMENT_PATH = ARENA_ROOT / "experiment.json"
ULTIMATE_DIR = REPO / "data" / "intelligence" / "ultimate_model"
PANEL_PATH = REPO / "data" / "predictions_v3" / "live.csv"

VERSIONS = ("v1", "v2")
FROZEN_VERSIONS = frozenset(VERSIONS)
MASTER_SEEDS = {"v1": 20260602, "v2": 20260620}


def is_frozen(version: str) -> bool:
    return version in FROZEN_VERSIONS


def _load_experiment_raw() -> dict:
    if EXPERIMENT_PATH.exists():
        try:
            return json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def list_versions() -> list[str]:
    exp = _load_experiment_raw()
    keys = sorted((exp.get("versions") or {}).keys(), key=lambda v: (len(v), v))
    return keys or list(VERSIONS)


def next_version_id() -> str:
    existing = list_versions()
    n = 3
    while f"v{n}" in existing:
        n += 1
    return f"v{n}"


def register_version(version: str, meta: dict) -> dict:
    """Add version metadata without modifying frozen version entries."""
    if is_frozen(version):
        raise ValueError(f"Cannot register over frozen arena {version}")
    exp = ensure_experiment()
    versions = dict(exp.get("versions") or {})
    versions[version] = {**(versions.get(version) or {}), **meta}
    exp["versions"] = versions
    exp["versionList"] = sorted(versions.keys(), key=lambda v: (len(v), v))
    if version not in MASTER_SEEDS:
        n = int(version[1:]) if version[1:].isdigit() else 99
        MASTER_SEEDS[version] = 20260700 + n * 17
    EXPERIMENT_PATH.write_text(json.dumps(exp, indent=2), encoding="utf-8")
    return exp


def update_version_meta(version: str, patch: dict) -> dict:
    """Update experiment metadata for a mutable (v3+) arena."""
    if is_frozen(version):
        raise ValueError(f"Cannot update frozen arena {version}")
    exp = ensure_experiment()
    versions = dict(exp.get("versions") or {})
    versions[version] = {**(versions.get(version) or {}), **patch}
    exp["versions"] = versions
    EXPERIMENT_PATH.write_text(json.dumps(exp, indent=2), encoding="utf-8")
    return versions[version]


def latest_mutable_version() -> str | None:
    vers = [v for v in list_versions() if not is_frozen(v)]
    return vers[-1] if vers else None


def version_for_recommendation(rec_id: str) -> str | None:
    exp = _load_experiment_raw()
    for vid, meta in (exp.get("versions") or {}).items():
        if meta.get("sourceRecommendation") == rec_id:
            return vid
    return None


def backup_frozen_snapshot(version: str) -> str | None:
    """Save dated ledger copy for frozen v1/v2 before daily pulse."""
    if not is_frozen(version):
        return None
    src = ledger_path(version)
    if not src.exists():
        return None
    snap_dir = ARENA_ROOT / "snapshots" / version
    snap_dir.mkdir(parents=True, exist_ok=True)
    dest = snap_dir / f"{_today()}.json"
    if not dest.exists():
        shutil.copy2(src, dest)
    return str(dest.relative_to(REPO).as_posix())


def version_panel_path(version: str) -> Path:
    exp = _load_experiment_raw()
    meta = (exp.get("versions") or {}).get(version) or {}
    raw = meta.get("panelPath")
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else REPO / raw
    return PANEL_PATH


def version_dir(version: str) -> Path:
    return ARENA_ROOT / version


def traders_path(version: str) -> Path:
    return version_dir(version) / "traders.json"


def leaderboard_path(version: str) -> Path:
    return version_dir(version) / "leaderboard.json"


def ledger_path(version: str) -> Path:
    return version_dir(version) / "ledger.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def migrate_legacy() -> None:
    """Move pre-version arena files into v1/."""
    legacy_traders = ARENA_ROOT / "traders.json"
    if not legacy_traders.exists():
        return
    v1 = version_dir("v1")
    v1.mkdir(parents=True, exist_ok=True)
    for name in ("traders.json", "leaderboard.json"):
        src = ARENA_ROOT / name
        dst = v1 / name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
    if not ledger_path("v1").exists() and leaderboard_path("v1").exists():
        try:
            from .ledger import init_ledger_from_leaderboard
            init_ledger_from_leaderboard("v1")
        except (OSError, json.JSONDecodeError, RecursionError, ValueError):
            pass


def ensure_experiment() -> dict:
    migrate_legacy()
    ARENA_ROOT.mkdir(parents=True, exist_ok=True)
    if EXPERIMENT_PATH.exists():
        try:
            doc = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8-sig"))
            doc.setdefault("versionList", sorted((doc.get("versions") or {}).keys(), key=lambda v: (len(v), v)))
            return doc
        except (OSError, json.JSONDecodeError):
            pass
    doc = {
        "startedAt": _now(),
        "label": "Investor Arena A/B — v1 threshold vs v2 rank-unified",
        "initialEquityUsd": 50_000,
        "versions": {
            "v1": {"startedAt": _now(), "nTraders": 100, "frozen": True, "selectionMode": "threshold_v1"},
            "v2": {"startedAt": _now(), "nTraders": 100, "frozen": True, "selectionMode": "rank_v2"},
        },
        "versionList": list(VERSIONS),
    }
    EXPERIMENT_PATH.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc
