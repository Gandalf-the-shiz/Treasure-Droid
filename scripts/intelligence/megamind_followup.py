"""Email follow-up after Megamind debug pass (clean bill of health)."""
from __future__ import annotations

import json
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_ROOT = Path(r"c:\Users\nicho\nostradamus-live")
MEGAMIND_DIR = REPO / "data" / "intelligence" / "megamind"


def _smtp_config() -> dict | None:
    cfg = {
        "host": os.environ.get("NOSTRA_SMTP_HOST"),
        "port": os.environ.get("NOSTRA_SMTP_PORT"),
        "username": os.environ.get("NOSTRA_SMTP_USER"),
        "password": os.environ.get("NOSTRA_SMTP_PASS"),
        "from": os.environ.get("NOSTRA_SMTP_FROM"),
        "to": os.environ.get("NOSTRA_SMTP_TO"),
    }
    path = LIVE_ROOT / "config" / "email.json"
    if path.exists():
        try:
            file_cfg = json.loads(path.read_text(encoding="utf-8-sig"))
            for k, v in file_cfg.items():
                if v and not cfg.get(k):
                    cfg[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    if not (cfg.get("host") and cfg.get("username") and cfg.get("password") and cfg.get("to")):
        return None
    cfg["port"] = int(cfg.get("port") or 587)
    return cfg


def _gather_context(pending: dict, debug_report: dict) -> dict:
    reg = {}
    reg_path = MEGAMIND_DIR / "registry.json"
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8-sig"))
    rid = pending.get("recommendationId")
    entry = (reg.get("recommendations") or {}).get(rid) or {}
    exp = {}
    exp_path = REPO / "data" / "trader_arena" / "experiment.json"
    if exp_path.exists():
        exp = json.loads(exp_path.read_text(encoding="utf-8-sig"))
    sdk = {}
    sdk_path = MEGAMIND_DIR / "last_sdk_run.json"
    if sdk_path.exists():
        sdk = json.loads(sdk_path.read_text(encoding="utf-8-sig"))
    cfg_path = REPO / "config" / "megamind.json"
    public_url = ""
    if cfg_path.exists():
        c = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        public_url = c.get("publicDashboardUrl") or c.get("dashboardBaseUrl") or ""
    return {
        "rid": rid,
        "entry": entry,
        "exp": exp,
        "sdk": sdk,
        "debug": debug_report,
        "arena_action": pending.get("arenaAction") or {},
        "public_url": public_url.rstrip("/"),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


def render_followup(ctx: dict) -> tuple[str, str, str]:
    e = ctx["entry"]
    aa = ctx["arena_action"] or {}
    vers = (ctx["exp"].get("versionList") or [])
    subject = f"Megamind complete — {e.get('area', 'task')} — debug OK"
    lines = [
        f"Megamind follow-up ({ctx['ts']})",
        "",
        f"Recommendation: {ctx['rid']}",
        f"  Area: {e.get('area')} · Priority: {e.get('priority')}",
        f"  Approved: {e.get('approvedAt')} via {e.get('approvedVia', '?')}",
        "",
        "SDK / agent:",
        f"  Status: {ctx['sdk'].get('status', 'n/a (IDE or pending)')}",
        "",
        "Arena (v1/v2 frozen, daily pulse + snapshots):",
    ]
    if aa.get("updated"):
        lines.append(f"  Updated {aa.get('version')} in place (no respawn).")
    elif aa.get("spawned"):
        lines.append(f"  Spawned new arm {aa.get('version')}.")
    else:
        lines.append("  No arena spawn/update for this task.")
    lines.append(f"  Active arms: {', '.join(vers)}")
    lines.append("")
    lines.append("Debug agent: all checks passed.")
    for name, chk in (ctx["debug"].get("checks") or {}).items():
        lines.append(f"  - {name}: {chk.get('detail')}")
    if ctx["public_url"]:
        lines.append(f"\nDashboard: {ctx['public_url']}/#/megamind")
    text = "\n".join(lines)

    html = f"""<html><body style="font-family:sans-serif;max-width:640px;padding:16px">
    <h2 style="color:#00c805">Megamind run complete</h2>
    <p><b>{ctx['ts']}</b> — debug agent found no issues.</p>
    <h3>Recommendation</h3>
    <ul>
      <li><b>ID:</b> {ctx['rid']}</li>
      <li><b>Area:</b> {e.get('area')} ({e.get('priority')})</li>
      <li><b>Approved:</b> {e.get('approvedVia', '?')} at {e.get('approvedAt', '')}</li>
    </ul>
    <h3>Agent</h3>
    <p>SDK status: <code>{ctx['sdk'].get('status', 'n/a')}</code></p>
    <h3>Arena</h3>
    <p>{'Updated <b>' + str(aa.get('version')) + '</b> (in place).' if aa.get('updated') else (
        'Spawned <b>' + str(aa.get('version')) + '</b>.' if aa.get('spawned') else 'No arena change.')}</p>
    <p>Arms: {', '.join(vers)} · v1/v2 frozen with daily snapshots</p>
    <h3>Debug checks</h3>
    <ul>{''.join(f"<li>{k}: {v.get('detail')}</li>" for k, v in (ctx['debug'].get('checks') or {}).items())}</ul>
    {f'<p><a href="{ctx["public_url"]}/#/megamind">Open Megamind</a></p>' if ctx['public_url'] else ''}
    </body></html>"""
    return subject, text, html


def send_followup_email(pending: dict, debug_report: dict) -> dict:
    if not debug_report.get("passed"):
        return {"sent": False, "reason": "debug found issues — no success email"}
    smtp = _smtp_config()
    if not smtp:
        return {"sent": False, "reason": "no SMTP config"}
    ctx = _gather_context(pending, debug_report)
    subject, text, html = render_followup(ctx)
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp["from"]
    msg["To"] = smtp["to"]
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    ctx_ssl = ssl.create_default_context()
    with smtplib.SMTP(smtp["host"], smtp["port"], timeout=30) as server:
        server.starttls(context=ctx_ssl)
        server.login(smtp["username"], smtp["password"])
        server.sendmail(smtp["from"], [a.strip() for a in smtp["to"].split(",")], msg.as_string())
    out_path = MEGAMIND_DIR / "last_followup_email.json"
    out_path.write_text(
        json.dumps({"sent": True, "subject": subject, "to": smtp["to"]}, indent=2),
        encoding="utf-8",
    )
    print(f"[megamind-followup] email sent to {smtp['to']}", flush=True)
    return {"sent": True, "to": smtp["to"], "subject": subject}


def main() -> int:
    pending_path = MEGAMIND_DIR / "pending_for_agent.json"
    debug_path = MEGAMIND_DIR / "last_debug_report.json"
    if not pending_path.exists() or not debug_path.exists():
        print("[megamind-followup] missing pending or debug report", flush=True)
        return 1
    pending = json.loads(pending_path.read_text(encoding="utf-8-sig"))
    debug_report = json.loads(debug_path.read_text(encoding="utf-8-sig"))
    print(json.dumps(send_followup_email(pending, debug_report), indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
