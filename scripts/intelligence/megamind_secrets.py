"""Load Megamind secrets (gitignored) into environment."""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SECRETS = REPO / "config" / "megamind.secrets.json"


def load_into_env() -> dict:
    if SECRETS.exists():
        try:
            doc = json.loads(SECRETS.read_text(encoding="utf-8-sig"))
            key = (doc.get("cursorApiKey") or "").strip()
            if key and not os.environ.get("CURSOR_API_KEY"):
                os.environ["CURSOR_API_KEY"] = key
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "hasApiKey": bool(os.environ.get("CURSOR_API_KEY")),
        "secretsFile": str(SECRETS),
        "secretsExists": SECRETS.exists(),
    }
