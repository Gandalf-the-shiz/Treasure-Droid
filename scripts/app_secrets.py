"""Central secret loader. Env vars win; falls back to gitignored config/secrets.json.

Never hardcode keys in code. Import and call load_secrets() early, or use
get_secret("FINNHUB_API_KEY").
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SECRETS_PATH = _REPO / "config" / "secrets.json"
_loaded = False


def load_secrets(override: bool = False) -> dict:
    """Populate os.environ from config/secrets.json without clobbering real env vars."""
    global _loaded
    data: dict = {}
    if _SECRETS_PATH.exists():
        try:
            data = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[secrets] could not read {_SECRETS_PATH}: {exc}", flush=True)
            data = {}
    for k, v in data.items():
        if k.startswith("_") or v in (None, ""):
            continue
        if override or not os.environ.get(k):
            os.environ[k] = str(v)
    _loaded = True
    return data


def get_secret(name: str, default: str | None = None) -> str | None:
    if not _loaded:
        load_secrets()
    val = os.environ.get(name)
    return val if val not in (None, "") else default
