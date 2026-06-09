"""Lightweight debug pass after Megamind agent / SDK completes."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

REPO = Path(__file__).resolve().parents[2]
MEGAMIND_DIR = REPO / "data" / "intelligence" / "megamind"
REPORT_PATH = MEGAMIND_DIR / "last_debug_report.json"


def _check_health() -> dict:
    try:
        with urlopen("http://127.0.0.1:8000/api/health", timeout=5) as resp:
            return {"ok": resp.status == 200, "detail": "serve.py health"}
    except OSError as exc:
        return {"ok": False, "detail": f"serve unreachable: {exc}"}


def _check_arena() -> dict:
    exp_path = REPO / "data" / "trader_arena" / "experiment.json"
    try:
        exp = json.loads(exp_path.read_text(encoding="utf-8-sig"))
        vers = exp.get("versionList") or []
        frozen = [v for v in vers if (exp.get("versions") or {}).get(v, {}).get("frozen")]
        return {"ok": True, "detail": f"arena arms: {', '.join(vers)}; frozen: {', '.join(frozen)}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": f"experiment.json: {exc}"}


def _check_sdk_run(rid: str | None) -> dict:
    p = MEGAMIND_DIR / "last_sdk_run.json"
    if not p.exists():
        return {"ok": True, "detail": "no SDK run log (IDE-only approval)"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
        status = str(doc.get("status", "")).lower()
        if rid and doc.get("recommendationId") not in (rid, None):
            return {"ok": True, "detail": f"sdk log for {doc.get('recommendationId')}"}
        if status in ("error", "failed", "cancelled"):
            return {"ok": False, "detail": f"SDK status={doc.get('status')}"}
        return {"ok": True, "detail": f"SDK status={doc.get('status')}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": str(exc)}


def _check_registry(rid: str | None) -> dict:
    reg_path = MEGAMIND_DIR / "registry.json"
    if not rid:
        return {"ok": True, "detail": "no recommendation id"}
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8-sig"))
        entry = (reg.get("recommendations") or {}).get(rid)
        if not entry:
            return {"ok": False, "detail": f"missing registry entry {rid}"}
        if entry.get("status") != "approved":
            return {"ok": False, "detail": f"status={entry.get('status')}"}
        return {"ok": True, "detail": f"approved via {entry.get('approvedVia', '?')}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False, "detail": str(exc)}


def _check_syntax() -> dict:
    targets = [
        REPO / "scripts" / "intelligence" / "megamind.py",
        REPO / "scripts" / "intelligence" / "arena" / "mutable.py",
        REPO / "scripts" / "serve.py",
    ]
    failed = []
    for t in targets:
        if not t.exists():
            continue
        r = subprocess.run(
            [sys.executable, "-m", "py_compile", str(t)],
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        if r.returncode != 0:
            failed.append(t.name)
    if failed:
        return {"ok": False, "detail": f"py_compile failed: {', '.join(failed)}"}
    return {"ok": True, "detail": "core modules compile"}


def run_debug_agent(pending: dict | None = None) -> dict:
    pending = pending or {}
    rid = pending.get("recommendationId")
    checks = {
        "health": _check_health(),
        "arena": _check_arena(),
        "registry": _check_registry(rid),
        "sdk": _check_sdk_run(rid),
        "syntax": _check_syntax(),
    }
    issues = [f"{k}: {v['detail']}" for k, v in checks.items() if not v.get("ok")]
    report = {
        "recommendationId": rid,
        "checks": checks,
        "issues": issues,
        "passed": len(issues) == 0,
        "pending": {
            "queuedAt": pending.get("queuedAt"),
            "arenaAction": pending.get("arenaAction"),
        },
    }
    sdk_err = MEGAMIND_DIR / "last_sdk_error.txt"
    if sdk_err.exists() and sdk_err.read_text(encoding="utf-8").strip():
        report["issues"].append(f"sdk_error: {sdk_err.read_text(encoding='utf-8')[:500]}")
        report["passed"] = False

    MEGAMIND_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[megamind-debug] passed={report['passed']} issues={len(report['issues'])}", flush=True)
    return report
