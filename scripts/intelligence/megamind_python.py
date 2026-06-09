"""Resolve Python executable for Megamind SDK (cursor-sdk needs win-amd64)."""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config" / "megamind.json"
EMBED_PY = REPO / "tools" / "python311-amd64" / "python.exe"


def sdk_python() -> Path | None:
    if CONFIG.exists():
        try:
            cfg = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
            raw = (cfg.get("sdkPython") or "").strip()
            if raw:
                p = Path(raw)
                if p.is_file():
                    return p
        except (OSError, json.JSONDecodeError):
            pass
    if EMBED_PY.is_file():
        return EMBED_PY
    if platform.machine().upper() in ("AMD64", "X86_64"):
        return Path(sys.executable)
    return None


def agent_executable() -> str:
    p = sdk_python()
    return str(p) if p else sys.executable


def main() -> int:
    p = sdk_python()
    if p:
        print(p)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
