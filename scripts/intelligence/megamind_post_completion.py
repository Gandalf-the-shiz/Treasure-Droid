"""After Megamind SDK/agent finishes: debug pass, then follow-up email if clean."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PENDING = REPO / "data" / "intelligence" / "megamind" / "pending_for_agent.json"


def _config() -> dict:
    p = REPO / "config" / "megamind.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def run_post_completion() -> dict:
    cfg = _config()
    if not cfg.get("postCompletionEnabled", True):
        return {"skipped": True, "reason": "postCompletionEnabled=false"}

    if not PENDING.exists():
        return {"skipped": True, "reason": "no pending_for_agent.json"}

    pending = json.loads(PENDING.read_text(encoding="utf-8-sig"))
    if not pending.get("sdkCompletedAt") and not pending.get("forcePostCompletion"):
        return {"skipped": True, "reason": "SDK not marked complete (waiting)"}

    if pending.get("postCompletionAt"):
        return {"skipped": True, "reason": "already ran post-completion"}

    from intelligence.megamind_debug_agent import run_debug_agent
    from intelligence.megamind_followup import send_followup_email

    debug_report = run_debug_agent(pending)
    email_result = {"sent": False}
    if debug_report.get("passed") and cfg.get("followupEmailEnabled", True):
        email_result = send_followup_email(pending, debug_report)
    elif not debug_report.get("passed"):
        email_result = {"sent": False, "reason": "debug issues — see last_debug_report.json"}

    pending["postCompletionAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    pending["debugPassed"] = debug_report.get("passed")
    pending["followupEmail"] = email_result
    PENDING.write_text(json.dumps(pending, indent=2), encoding="utf-8")

    return {"debug": debug_report, "email": email_result}


def main() -> int:
    out = run_post_completion()
    print(json.dumps({k: v for k, v in out.items() if k != "debug"}, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
