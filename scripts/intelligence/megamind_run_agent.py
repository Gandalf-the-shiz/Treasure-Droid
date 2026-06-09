"""Treasure Droid auto-coder — implement an approved recommendation autonomously.

Robust by design on this Windows ARM64 box:
  - The cursor-sdk LOCAL runtime is broken here (WinError 10038 socket) and the
    headless cursor-agent CLI isn't installed, so we never call the local runtime.
  - autoBuildMode == "cloud": run a Cursor CLOUD agent (no local sockets) against
    the GitHub repo and open a PR.
  - autoBuildMode == "ide" (default): do nothing here — approval already wrote the
    prompt + always-on rule and opened Cursor for a one-click build.
Always writes a status to last_autobuild.json and never crashes the approve flow.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

MM_DIR = REPO / "data" / "intelligence" / "megamind"
PENDING = MM_DIR / "pending_for_agent.json"
PROMPT = MM_DIR / "CURRENT_AGENT_PROMPT.md"
STATUS = MM_DIR / "last_autobuild.json"
CONFIG = REPO / "config" / "megamind.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cfg() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _mode(cfg: dict) -> str:
    return (cfg.get("autoBuildMode") or "ide").strip().lower()


def _repo_slug() -> str | None:
    try:
        url = subprocess.check_output(["git", "remote", "get-url", "origin"], cwd=str(REPO),
                                      text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None
    m = re.search(r"github\.com[/:]([^/\s]+/[^/\s]+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def _write_status(doc: dict) -> None:
    doc["updatedAt"] = _now()
    MM_DIR.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def _run_cloud(prompt: str, model: str, repo: str, api_key: str) -> dict:
    from cursor_sdk import Agent, AgentOptions, CloudAgentOptions, CursorAgentError

    try:
        try:
            cloud = CloudAgentOptions(repos=[repo], auto_create_pr=True)
        except TypeError:
            cloud = CloudAgentOptions(repos=[repo])
        result = Agent.prompt(prompt, AgentOptions(api_key=api_key, model=model, cloud=cloud))
        return {
            "ok": True, "mode": "cloud", "status": str(getattr(result, "status", "unknown")),
            "agentId": getattr(result, "agent_id", None) or getattr(result, "id", None),
            "result": str(getattr(result, "result", ""))[:4000],
        }
    except CursorAgentError as exc:
        return {"ok": False, "mode": "cloud", "stage": "startup", "error": str(exc)[:400],
                "retryable": bool(getattr(exc, "is_retryable", False))}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": "cloud", "stage": "run", "error": str(exc)[:400]}


def main() -> int:
    cfg = _cfg()
    mode = _mode(cfg)
    dry = "--dry" in sys.argv

    if not PENDING.exists() or not PROMPT.exists():
        _write_status({"mode": mode, "ok": False, "reason": "nothing pending"})
        print("[auto-coder] nothing pending", flush=True)
        return 0

    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    rid = pending.get("recommendationId")

    if mode != "cloud":
        _write_status({"mode": "ide", "ok": True, "recommendationId": rid,
                       "note": "IDE handoff — prompt + active rule written; one-click build in Cursor."})
        print("[auto-coder] IDE handoff (autoBuildMode=ide); no headless build", flush=True)
        return 0

    repo = _repo_slug()
    model = cfg.get("cursorModel") or "composer-2.5"
    from intelligence.megamind_secrets import load_into_env
    meta = load_into_env()
    import os
    api_key = os.environ.get("CURSOR_API_KEY") or cfg.get("cursorApiKey")

    if dry:
        print(json.dumps({"mode": mode, "repo": repo, "model": model,
                          "hasApiKey": bool(api_key), "rid": rid}, indent=2))
        return 0

    if not (repo and api_key):
        _write_status({"mode": "cloud", "ok": False, "recommendationId": rid,
                       "reason": f"missing {'repo' if not repo else 'api_key'}"})
        print("[auto-coder] cloud unavailable (repo/key) — left for IDE handoff", flush=True)
        return 1
    if pending.get("autoBuildAt"):
        print("[auto-coder] already built for this task", flush=True)
        return 0

    print(f"[auto-coder] cloud agent ({model}) on {repo} \u2014 opening PR...", flush=True)
    res = _run_cloud(PROMPT.read_text(encoding="utf-8"), model, repo, api_key)
    res["recommendationId"] = rid
    _write_status(res)
    pending["autoBuildAt"] = _now()
    pending["autoBuild"] = res
    PENDING.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    print(f"[auto-coder] cloud result ok={res.get('ok')} status={res.get('status') or res.get('error')}", flush=True)
    return 0 if res.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
