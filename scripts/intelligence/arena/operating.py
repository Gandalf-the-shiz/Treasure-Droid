"""Three-pool operating model: frozen v1/v2, champion v3+, optional challenger.

- Pulse only active versions (saves CPU; archived pools still feed harvest).
- Consolidate duplicate mutable forks (v4–v6 sprawl) without touching v1/v2 files.
"""
from __future__ import annotations

import json
from pathlib import Path

from .paths import (
    ARENA_ROOT,
    EXPERIMENT_PATH,
    _load_experiment_raw,
    _now,
    is_frozen,
    latest_mutable_version,
    list_versions,
    traders_path,
)

CHAMPION_DEFAULT = "v3"
CHAMPION_POPULATION = 112
MAX_ACTIVE_MUTABLE_PULSED = 2


def _save_experiment(exp: dict) -> None:
    ARENA_ROOT.mkdir(parents=True, exist_ok=True)
    exp["versionList"] = sorted((exp.get("versions") or {}).keys(), key=lambda v: (len(v), v))
    EXPERIMENT_PATH.write_text(json.dumps(exp, indent=2), encoding="utf-8")


def is_archived(version: str) -> bool:
    meta = (_load_experiment_raw().get("versions") or {}).get(version) or {}
    return bool(meta.get("archived"))


def version_role(version: str) -> str:
    meta = (_load_experiment_raw().get("versions") or {}).get(version) or {}
    return str(meta.get("role") or ("frozen" if is_frozen(version) else "mutable"))


def champion_version() -> str | None:
    exp = _load_experiment_raw()
    om = exp.get("operatingModel") or {}
    vid = om.get("champion")
    if vid and traders_path(vid).exists() and not is_archived(vid):
        return vid
    for v in list_versions():
        if is_frozen(v) or is_archived(v):
            continue
        meta = (exp.get("versions") or {}).get(v) or {}
        if meta.get("role") == "champion" and traders_path(v).exists():
            return v
    # Prefer v3 if present
    if traders_path(CHAMPION_DEFAULT).exists() and not is_archived(CHAMPION_DEFAULT):
        return CHAMPION_DEFAULT
    for v in list_versions():
        if not is_frozen(v) and not is_archived(v) and traders_path(v).exists():
            if version_role(v) != "challenger":
                return v
    return latest_mutable_version()


def challenger_version() -> str | None:
    exp = _load_experiment_raw()
    om = exp.get("operatingModel") or {}
    vid = om.get("challenger")
    if vid and traders_path(vid).exists() and not is_archived(vid):
        return vid
    for v in list_versions():
        if is_frozen(v) or is_archived(v):
            continue
        if version_role(v) == "challenger" and traders_path(v).exists():
            return v
    return None


def pulse_versions() -> list[str]:
    """Versions that receive scheduled pulses: v1, v2, champion, optional challenger."""
    out = ["v1", "v2"]
    champ = champion_version()
    if champ:
        out.append(champ)
    chall = challenger_version()
    if chall and chall not in out:
        out.append(chall)
    return out


def active_mutable_versions() -> list[str]:
    """Non-archived mutable arms (champion + challenger), max 2 pulsed."""
    out = []
    c = champion_version()
    if c:
        out.append(c)
    ch = challenger_version()
    if ch and ch not in out:
        out.append(ch)
    return out[:MAX_ACTIVE_MUTABLE_PULSED]


def archive_version(version: str, *, reason: str = "") -> dict:
    if is_frozen(version):
        raise ValueError(f"Cannot archive frozen arena {version}")
    exp = _load_experiment_raw()
    versions = dict(exp.get("versions") or {})
    if version not in versions:
        raise ValueError(f"Unknown arena {version}")
    versions[version] = {
        **versions[version],
        "archived": True,
        "archivedAt": _now(),
        "archiveReason": reason or "operating model consolidation",
        "role": "archived",
        "pulsed": False,
    }
    exp["versions"] = versions
    om = dict(exp.get("operatingModel") or {})
    archived = list(om.get("archived") or [])
    if version not in archived:
        archived.append(version)
    om["archived"] = sorted(archived, key=lambda v: (len(v), v))
    if om.get("challenger") == version:
        om["challenger"] = None
    exp["operatingModel"] = om
    _save_experiment(exp)
    return versions[version]


def set_champion(version: str) -> None:
    if is_frozen(version):
        raise ValueError(f"Cannot set frozen {version} as champion")
    exp = _load_experiment_raw()
    versions = dict(exp.get("versions") or {})
    for vid, meta in versions.items():
        if is_frozen(vid) or is_archived(vid):
            continue
        m = dict(meta)
        if vid == version:
            m["role"] = "champion"
            m["archived"] = False
            m.pop("archivedAt", None)
        elif m.get("role") == "champion" and vid != version:
            m["role"] = "mutable"
        versions[vid] = m
    versions[version] = {**(versions.get(version) or {}), "role": "champion", "archived": False}
    om = dict(exp.get("operatingModel") or {})
    om["champion"] = version
    exp["operatingModel"] = om
    exp["versions"] = versions
    _save_experiment(exp)


def set_challenger(version: str | None) -> None:
    exp = _load_experiment_raw()
    om = dict(exp.get("operatingModel") or {})
    om["challenger"] = version
    if version:
        versions = dict(exp.get("versions") or {})
        versions[version] = {
            **(versions.get(version) or {}),
            "role": "challenger",
            "archived": False,
        }
        exp["versions"] = versions
    exp["operatingModel"] = om
    _save_experiment(exp)


def ensure_operating_model(*, force: bool = False) -> dict:
    """
    One-time style consolidation: v3 = champion; duplicate mutables archived for harvest-only.
    Never modifies v1/v2 trader files.
    """
    exp = _load_experiment_raw()
    if exp.get("operatingModel", {}).get("consolidated") and not force:
        return exp.get("operatingModel") or {}

    mutables = [v for v in list_versions() if not is_frozen(v)]
    champ = CHAMPION_DEFAULT if traders_path(CHAMPION_DEFAULT).exists() else None
    if not champ and mutables:
        # Pick earliest mutable with traders as champion
        for v in sorted(mutables, key=lambda x: (len(x), x)):
            if traders_path(v).exists():
                champ = v
                break

    archived: list[str] = []
    if champ:
        set_champion(champ)
        for v in mutables:
            if v == champ:
                continue
            if traders_path(v).exists():
                archive_version(
                    v,
                    reason="Duplicate mutable fork — harvest-only per operating model (v1/v2 untouched).",
                )
                archived.append(v)

    om = {
        "consolidated": True,
        "consolidatedAt": _now(),
        "champion": champ,
        "challenger": challenger_version(),
        "archived": archived,
        "pulseVersions": pulse_versions(),
        "championPopulation": CHAMPION_POPULATION,
        "maxActiveMutablePulsed": MAX_ACTIVE_MUTABLE_PULSED,
        "policy": (
            "Pulse v1+v2+champion(+optional challenger). Harvest all ledgers. "
            "Evolve champion population. Distill ≤5 real ML agents."
        ),
    }
    exp = _load_experiment_raw()
    exp["operatingModel"] = om
    _save_experiment(exp)
    print(
        f"[arena-operating] champion={champ} archived={archived} pulse={pulse_versions()}",
        flush=True,
    )
    return om


def operating_status() -> dict:
    ensure_operating_model()
    return {
        "champion": champion_version(),
        "challenger": challenger_version(),
        "pulseVersions": pulse_versions(),
        "activeMutable": active_mutable_versions(),
        "archived": [v for v in list_versions() if is_archived(v)],
        "operatingModel": _load_experiment_raw().get("operatingModel"),
    }
