"""Megamind — meta-agent (Ultimate Model) with approvable recommendations.

Produces research recommendations from arena + intelligence; you approve in the
dashboard or email link; approval queues an implementation brief for Cursor Agent.

Usage:
  python scripts/intelligence/megamind.py --tick
  python scripts/intelligence/megamind.py --approve <rec_id>
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

MEGAMIND_DIR = REPO / "data" / "intelligence" / "megamind"
REGISTRY_PATH = MEGAMIND_DIR / "registry.json"
REPORT_PATH = MEGAMIND_DIR / "latest_report.json"
CONFIG_PATH = REPO / "config" / "megamind.json"
TASKS_DIR = MEGAMIND_DIR / "tasks"
LATEST_TASK_MD = MEGAMIND_DIR / "LATEST_APPROVED.md"
PENDING_AGENT_PATH = MEGAMIND_DIR / "pending_for_agent.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        pass
    return default if default is not None else {}


def _save_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _config() -> dict:
    from intelligence.megamind_secrets import load_into_env
    load_into_env()
    cfg = _load_json(CONFIG_PATH, {})
    secret = cfg.get("approveSecret") or secrets.token_hex(16)
    if not CONFIG_PATH.exists():
        MEGAMIND_DIR.mkdir(parents=True, exist_ok=True)
        _save_json(CONFIG_PATH, {
            "approveSecret": secret,
            "dashboardBaseUrl": "http://127.0.0.1:8000",
            "autoLaunch": "both",
            "autoApproveEnabled": True,
            "autoApprovePriorities": ["critical", "high"],
            "cursorModel": "composer-2.5",
            "_note": "autoLaunch: ide | sdk | both | none. API key in config/megamind.secrets.json",
        })
    cfg = _load_json(CONFIG_PATH, {}) or cfg
    secrets_doc = _load_json(REPO / "config" / "megamind.secrets.json", {})
    if secrets_doc.get("cursorApiKey") and not cfg.get("cursorApiKey"):
        cfg["cursorApiKey"] = secrets_doc["cursorApiKey"]
    return cfg


def rec_id(rec: dict) -> str:
    raw = f"{rec.get('area', '')}|{rec.get('action', '')}|{rec.get('finding', '')[:120]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def approve_token(rid: str) -> str:
    secret = (_config().get("approveSecret") or "").encode()
    return hmac.new(secret, rid.encode(), hashlib.sha256).hexdigest()[:20]


def verify_token(rid: str, token: str) -> bool:
    if not token:
        return False
    expected = approve_token(rid)
    return hmac.compare_digest(expected, token)


def _is_loopback_host(host: str) -> bool:
    return (host or "").lower() in ("localhost", "127.0.0.1", "::1")


def public_base_url(cfg: dict | None = None) -> str:
    """Base URL for email approve links (phone / remote). Not the bind address."""
    cfg = cfg if cfg is not None else _config()
    env = (os.environ.get("MEGAMIND_PUBLIC_URL") or "").strip().rstrip("/")
    if env:
        return env
    tunnel_file = MEGAMIND_DIR / "tunnel_url.txt"
    if tunnel_file.exists():
        try:
            line = tunnel_file.read_text(encoding="utf-8-sig").strip().splitlines()[0].strip()
            if line.startswith("http"):
                return line.rstrip("/")
        except OSError:
            pass
    for field in ("publicDashboardUrl", "dashboardBaseUrl"):
        url = (cfg.get(field) or "").strip().rstrip("/")
        if not url:
            continue
        if not _is_loopback_host(urlparse(url).hostname or ""):
            return url
    return (cfg.get("dashboardBaseUrl") or "http://127.0.0.1:8000").rstrip("/")


def apply_public_urls(doc: dict, cfg: dict | None = None) -> dict:
    """Refresh approve/review URLs (call before daily email if public URL changed)."""
    cfg = cfg if cfg is not None else _config()
    base = public_base_url(cfg)
    out = {**doc, "dashboardUrl": f"{base}/#/megamind", "publicBaseUrl": base}
    recs = []
    for r in doc.get("recommendations") or []:
        row = dict(r)
        rid = row.get("id") or rec_id(row)
        row["id"] = rid
        row["approveToken"] = row.get("approveToken") or approve_token(rid)
        row["approveUrl"] = f"{base}/api/megamind/approve/{rid}?token={row['approveToken']}"
        row["reviewUrl"] = f"{base}/#/megamind?highlight={rid}"
        recs.append(row)
    out["recommendations"] = recs
    return out


def refresh_report_urls() -> dict:
    """Rewrite latest_report.json approve links from current public base URL."""
    doc = _load_json(REPORT_PATH, {})
    if not doc:
        raise FileNotFoundError("No Megamind report — run megamind.py --tick first")
    doc = apply_public_urls(doc)
    _save_json(REPORT_PATH, doc)
    ultimate_path = REPO / "data" / "intelligence" / "ultimate_model" / "latest_report.json"
    _save_json(ultimate_path, doc)
    print(f"[megamind] URLs refreshed -> {doc.get('publicBaseUrl')}", flush=True)
    return doc


def _load_registry() -> dict:
    doc = _load_json(REGISTRY_PATH, {"recommendations": {}, "updatedAt": None})
    doc.setdefault("recommendations", {})
    return doc


def _merge_recommendations(recs: list[dict]) -> list[dict]:
    reg = _load_registry()
    out = []
    for r in recs:
        rid = rec_id(r)
        prev = reg["recommendations"].get(rid, {})
        status = prev.get("status", "proposed")
        if status in ("implemented", "rejected"):
            merged = {**r, "id": rid, "status": status, **{k: prev[k] for k in ("approvedAt", "rejectedAt") if k in prev}}
        else:
            merged = {**r, "id": rid, "status": status}
        merged["approveToken"] = approve_token(rid)
        reg["recommendations"][rid] = {
            "id": rid,
            "area": r.get("area"),
            "priority": r.get("priority"),
            "finding": r.get("finding"),
            "action": r.get("action"),
            "status": status,
            "firstSeenAt": prev.get("firstSeenAt") or _now(),
            "lastSeenAt": _now(),
        }
        out.append(merged)
    reg["updatedAt"] = _now()
    _save_json(REGISTRY_PATH, reg)
    return out


def _build_agent_brief(rec: dict, report: dict) -> str:
    return f"""# Megamind approved implementation

**Approved at:** {_now()}
**Recommendation ID:** `{rec.get('id')}`
**Area:** {rec.get('area')}
**Priority:** {rec.get('priority')}

## Finding
{rec.get('finding')}

## Requested action
{rec.get('action')}

## Context (do not weaken live trading gates)
- Arena v1/v2 returns are **simulated** from pred_ret — not proof of forward edge.
- Paper-only unless readiness gate explicitly permits live.
- Prefer minimal, testable diffs; match existing repo conventions.

## Arena snapshot
- v2 beating v1: {(report.get('compare') or {}).get('v2BeatingV1')}
- v1 mean cumulative: {(report.get('v1') or {}).get('summary', {}).get('meanCumulativePct')}%
- v2 mean cumulative: {(report.get('v2') or {}).get('summary', {}).get('meanCumulativePct')}%

## Instructions for Cursor Agent
Implement the requested action above in `Nostradamus_remote_audit` (and `nostradamus-live` if email/UI touched).
When complete, mark this task implemented via API or set registry status to implemented.
"""


def approve_recommendation(rid: str, *, source: str = "dashboard") -> dict:
    reg = _load_registry()
    entry = reg["recommendations"].get(rid)
    if not entry:
        raise ValueError(f"unknown recommendation id: {rid}")

    report = _load_json(REPORT_PATH, {})
    rec = {**entry, "id": rid}
    for r in report.get("recommendations") or []:
        if rec_id(r) == rid:
            rec = {**r, "id": rid}
            break

    entry["status"] = "approved"
    entry["approvedAt"] = _now()
    entry["approvedVia"] = source
    reg["recommendations"][rid] = entry
    _save_json(REGISTRY_PATH, reg)

    from intelligence.megamind_prompt import build_cursor_prompt
    from intelligence.megamind_cursor import launch_into_cursor

    cursor_prompt = build_cursor_prompt(rec, report)
    brief = _build_agent_brief(rec, report)
    brief += f"\n\n---\n\n## Cursor Agent prompt (auto-generated)\n\n{cursor_prompt}\n"
    cfg = _config()
    launch = launch_into_cursor(cursor_prompt, rec, cfg)
    arena_action = None
    try:
        from intelligence.arena.mutable import apply_arena_from_recommendation

        arena_action = apply_arena_from_recommendation(rec, report)
        if arena_action:
            if arena_action.get("spawned"):
                print(f"[megamind] spawned arena {arena_action.get('version')}", flush=True)
            elif arena_action.get("updated"):
                dec = (arena_action.get("megamindDecision") or {}).get("reason", "")
                print(f"[megamind] updated arena {arena_action.get('version')} — {dec[:80]}", flush=True)
            elif arena_action.get("spawned") is False and arena_action.get("reason"):
                print(f"[megamind] arena: {arena_action.get('reason')}", flush=True)
    except Exception as exc:
        arena_action = {"error": str(exc), "spawned": False, "updated": False}
    if arena_action:
        launch["arenaAction"] = arena_action
    try:
        from intelligence.real_agents import run_operating_cycle
        launch["operatingCycle"] = run_operating_cycle(evolve=bool(arena_action and (arena_action.get("updated") or arena_action.get("spawned"))))
    except Exception as exc:
        launch["operatingCycle"] = {"error": str(exc)}
    if (cfg.get("autoBuildMode") or "ide").lower() == "cloud":
        # Cloud auto-coder only (local cursor-sdk runtime is broken on Win ARM64).
        import subprocess
        from intelligence.megamind_python import agent_executable

        subprocess.Popen(
            [agent_executable(), str(REPO / "scripts" / "intelligence" / "megamind_run_agent.py")],
            cwd=str(REPO),
            env={**__import__("os").environ, "PYTHONPATH": str(REPO / "scripts")},
        )
        launch["autoBuild"] = "cloud_started"
    else:
        launch["autoBuild"] = "ide_handoff"  # reliable one-click build in Cursor

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    task_path = TASKS_DIR / f"{rid}.json"
    task_doc = {
        "id": rid,
        "status": "approved_pending_implementation",
        "approvedAt": entry["approvedAt"],
        "source": source,
        "recommendation": rec,
        "briefPath": str(LATEST_TASK_MD.relative_to(REPO)),
        "cursorPromptPath": launch.get("promptPath"),
        "cursorLaunch": launch,
    }
    _save_json(task_path, task_doc)
    LATEST_TASK_MD.write_text(brief, encoding="utf-8")
    _save_json(PENDING_AGENT_PATH, {
        "queuedAt": _now(),
        "recommendationId": rid,
        "taskFile": str(task_path.relative_to(REPO)),
        "briefFile": str(LATEST_TASK_MD.relative_to(REPO)),
        "cursorPromptPath": launch.get("promptPath"),
        "cursorLaunch": launch,
        "arenaAction": arena_action,
        "prompt": cursor_prompt[:500],
    })

    if cfg.get("postCompletionOnApprove", True) and not __import__("os").environ.get("CURSOR_API_KEY"):
        pending_doc = _load_json(PENDING_AGENT_PATH, {})
        pending_doc["forcePostCompletion"] = True
        _save_json(PENDING_AGENT_PATH, pending_doc)
        import subprocess

        subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "intelligence" / "megamind_post_completion.py")],
            cwd=str(REPO),
            env={**__import__("os").environ, "PYTHONPATH": str(REPO / "scripts")},
        )

    print(f"[megamind] approved {rid} -> Cursor prompt + rule active", flush=True)
    return {
        "ok": True,
        "id": rid,
        "status": "approved",
        "taskFile": str(task_path),
        "cursorLaunch": launch,
        "composerHint": launch.get("composerHint"),
    }


def mark_implemented(rid: str) -> dict:
    from intelligence.megamind_cursor import clear_active_rule

    reg = _load_registry()
    if rid not in reg["recommendations"]:
        raise ValueError(f"unknown recommendation id: {rid}")
    reg["recommendations"][rid]["status"] = "implemented"
    reg["recommendations"][rid]["implementedAt"] = _now()
    _save_json(REGISTRY_PATH, reg)
    if PENDING_AGENT_PATH.exists():
        PENDING_AGENT_PATH.unlink()
    clear_active_rule()
    return {"ok": True, "id": rid, "status": "implemented"}


def reject_recommendation(rid: str) -> dict:
    reg = _load_registry()
    if rid not in reg["recommendations"]:
        raise ValueError(f"unknown recommendation id: {rid}")
    reg["recommendations"][rid]["status"] = "rejected"
    reg["recommendations"][rid]["rejectedAt"] = _now()
    _save_json(REGISTRY_PATH, reg)
    return {"ok": True, "id": rid, "status": "rejected"}


def auto_approve_high_priority(recs: list[dict]) -> None:
    """Auto-approve one critical/high recommendation per tick when enabled."""
    cfg = _config()
    if not cfg.get("autoApproveEnabled"):
        return
    allowed = set(cfg.get("autoApprovePriorities") or ["critical", "high"])
    order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
    candidates = [
        r for r in recs
        if r.get("status") == "proposed" and r.get("priority") in allowed
    ]
    candidates.sort(key=lambda x: order.get(x.get("priority"), 9))
    for r in candidates[:1]:
        try:
            approve_recommendation(r["id"], source="auto")
            print(
                f"[megamind] auto-approved {r['id']} ({r.get('priority')}) {r.get('area')}",
                flush=True,
            )
            # Auto-build (cloud) is launched inside approve_recommendation when
            # autoBuildMode==cloud; no separate (broken local) SDK spawn here.
        except ValueError:
            pass


def run_tick() -> dict:
    from intelligence.ultimate_model import run_tick as ultimate_tick

    base = ultimate_tick()
    base_recs = base.get("recommendations") or []
    recs = _merge_recommendations(base_recs)
    auto_approve_high_priority(recs)
    # Re-merge the SAME fresh recs to pick up status changes from auto-approve
    # (reads the registry for status; must NOT fall back to the stale saved report).
    recs = _merge_recommendations(base_recs)
    cfg = _config()
    doc = {
        **base,
        "agent": "Treasure Droid",
        "status": "scheming",
        "recommendations": recs,
        "nPending": sum(1 for r in recs if r.get("status") == "proposed"),
        "nApproved": sum(1 for r in recs if r.get("status") == "approved"),
        "autoApproveEnabled": bool(cfg.get("autoApproveEnabled")),
        "hasCursorApiKey": bool(os.environ.get("CURSOR_API_KEY")),
    }
    doc = apply_public_urls(doc, cfg)

    try:
        from intelligence.real_agents import run_operating_cycle
        doc["operatingCycle"] = run_operating_cycle(evolve=False)
    except Exception as exc:
        doc["operatingCycle"] = {"error": str(exc)}

    MEGAMIND_DIR.mkdir(parents=True, exist_ok=True)
    _save_json(REPORT_PATH, doc)
    # Keep ultimate_model path in sync for older consumers
    ultimate_path = REPO / "data" / "intelligence" / "ultimate_model" / "latest_report.json"
    ultimate_path.parent.mkdir(parents=True, exist_ok=True)
    _save_json(ultimate_path, doc)
    print(f"[megamind] {len(recs)} recommendations ({doc['nPending']} pending)", flush=True)
    return doc


def public_report() -> dict:
    p = REPORT_PATH if REPORT_PATH.exists() else REPO / "data" / "intelligence" / "ultimate_model" / "latest_report.json"
    if not p.exists():
        raise FileNotFoundError("megamind not run yet")
    doc = _load_json(p)
    # Do not expose raw approve tokens in list API; dashboard uses POST with session on localhost
    safe = json.loads(json.dumps(doc))
    for r in safe.get("recommendations") or []:
        r.pop("approveToken", None)
        r.pop("approveUrl", None)
    return safe


def main() -> int:
    ap = argparse.ArgumentParser(description="Megamind meta-agent")
    ap.add_argument("--tick", action="store_true")
    ap.add_argument("--refresh-urls", action="store_true", help="Rewrite approve links for email/phone")
    ap.add_argument("--approve", metavar="ID")
    ap.add_argument("--reject", metavar="ID")
    args = ap.parse_args()
    if args.refresh_urls:
        refresh_report_urls()
    elif args.approve:
        approve_recommendation(args.approve, source="cli")
    elif args.reject:
        reject_recommendation(args.reject)
    elif args.tick:
        run_tick()
    else:
        run_tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
