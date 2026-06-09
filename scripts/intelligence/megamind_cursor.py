"""Launch approved Megamind work into Cursor (SDK, IDE, rules, hooks)."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO / "data" / "intelligence" / "megamind" / "CURRENT_AGENT_PROMPT.md"
RULE_PATH = REPO / ".cursor" / "rules" / "megamind-active-task.mdc"
CURSOR_DIR = REPO / ".cursor" / "megamind"


def _cursor_exe(cfg: dict) -> str | None:
    for cand in (
        cfg.get("cursorPath"),
        os.environ.get("CURSOR_CLI"),
        r"C:\Users\nicho\AppData\Local\Programs\cursor\resources\app\bin\cursor.cmd",
        "cursor",
    ):
        if not cand:
            continue
        p = Path(str(cand))
        if p.exists():
            return str(p)
    return None


def write_active_rule(prompt: str, rec_id: str, area: str) -> Path:
    RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "---\n"
        "description: ACTIVE Megamind approved task — implement this before other feature work\n"
        "alwaysApply: true\n"
        "---\n\n"
        f"> **Megamind task `{rec_id}`** ({area}) — auto-loaded because you approved this recommendation.\n"
        f"> Say **\"implement the Megamind task\"** or work through the prompt below.\n"
        f"> Clear this rule when done (approve flow sets status implemented).\n\n"
        f"{prompt}\n"
    )
    RULE_PATH.write_text(body, encoding="utf-8")
    return RULE_PATH


def clear_active_rule() -> None:
    if RULE_PATH.exists():
        RULE_PATH.unlink()


def open_in_cursor(prompt_path: Path, cfg: dict) -> dict:
    exe = _cursor_exe(cfg)
    if not exe:
        return {"opened": False, "reason": "cursor CLI not found"}
    try:
        subprocess.Popen(
            [exe, "-r", str(REPO), "-g", f"{prompt_path.relative_to(REPO).as_posix()}:1"],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {"opened": True, "cursor": exe}
    except OSError as exc:
        return {"opened": False, "reason": str(exc)}


def launch_sdk_agent(prompt: str, cfg: dict) -> dict:
    import platform

    # The local cursor-sdk runtime crashes on Windows ARM64 (WinError 10038 socket).
    # Never invoke it; autonomous builds go through the cloud runner (autoBuildMode=cloud).
    if platform.machine().upper() == "ARM64":
        return {"sdk": False, "reason": "local cursor-sdk unsupported on Windows ARM64 — use autoBuildMode=cloud or IDE handoff"}

    from intelligence.megamind_secrets import load_into_env
    load_into_env()
    api_key = os.environ.get("CURSOR_API_KEY") or cfg.get("cursorApiKey")
    if not api_key:
        return {"sdk": False, "reason": "CURSOR_API_KEY not set (see config/megamind.secrets.json)"}
    model = cfg.get("cursorModel") or "composer-2.5"

    def _run() -> None:
        try:
            from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    api_key=api_key,
                    model=model,
                    local=LocalAgentOptions(cwd=str(REPO)),
                ),
            )
            log = CURSOR_DIR / "last_sdk_run.json"
            CURSOR_DIR.mkdir(parents=True, exist_ok=True)
            log.write_text(
                json.dumps({"status": str(result.status), "result": str(result.result)[:4000]}, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            err = CURSOR_DIR / "last_sdk_error.txt"
            CURSOR_DIR.mkdir(parents=True, exist_ok=True)
            err.write_text(str(exc), encoding="utf-8")

    if cfg.get("sdkBlocking"):
        _run()
        return {"sdk": True, "mode": "blocking", "model": model}
    threading.Thread(target=_run, name="megamind-sdk", daemon=True).start()
    return {"sdk": True, "mode": "background", "model": model}


def launch_into_cursor(prompt: str, rec: dict, cfg: dict) -> dict:
    """Full handoff: prompt file, always-on rule, IDE open, optional SDK agent."""
    CURSOR_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_PATH.write_text(prompt, encoding="utf-8")

    rid = rec.get("id", "unknown")
    rule = write_active_rule(prompt, rid, rec.get("area", "general"))
    out = {
        "promptPath": str(PROMPT_PATH.relative_to(REPO)),
        "rulePath": str(rule.relative_to(REPO)),
        "autoLaunch": cfg.get("autoLaunch", "ide"),
    }

    mode = (cfg.get("autoLaunch") or "ide").lower()
    if mode in ("sdk", "both"):
        out["sdk"] = launch_sdk_agent(prompt, cfg)
    if mode in ("ide", "both", "file"):
        out["ide"] = open_in_cursor(PROMPT_PATH, cfg)
    if mode == "none":
        out["note"] = "Files written only; open CURRENT_AGENT_PROMPT.md manually"

    out["composerHint"] = (
        "In Cursor Agent, send: Implement the Megamind active task in "
        ".cursor/rules/megamind-active-task.mdc (or @CURRENT_AGENT_PROMPT.md)"
    )
    return out
