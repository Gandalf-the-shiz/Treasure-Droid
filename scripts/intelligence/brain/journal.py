"""Treasure Droid brain journal — backtest run log (last 30) + dev changelog.

Backtest entries append automatically from harness, mad scientist lab, fleet
walk-forward, and investor v3 training. Dev changelog is updated when agents
work on the app (via API or direct JSON edit).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
BRAIN_DIR = REPO / "data" / "intelligence" / "brain"
BACKTEST_LOG = BRAIN_DIR / "backtest_log.jsonl"
DEV_CHANGELOG = BRAIN_DIR / "dev_changelog.json"
MAX_BACKTESTS = 30


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_dirs() -> None:
    BRAIN_DIR.mkdir(parents=True, exist_ok=True)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    _ensure_dirs()
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def append_backtest(entry: dict) -> dict:
    """Append a backtest insight; keep only the last MAX_BACKTESTS runs."""
    _ensure_dirs()
    row = {
        "id": entry.get("id") or str(uuid.uuid4())[:12],
        "at": entry.get("at") or _now(),
        **{k: v for k, v in entry.items() if k not in ("id", "at")},
    }
    rows = _read_jsonl(BACKTEST_LOG)
    rows.append(row)
    if len(rows) > MAX_BACKTESTS:
        rows = rows[-MAX_BACKTESTS:]
    _write_jsonl(BACKTEST_LOG, rows)
    print(f"[brain-journal] backtest logged: {row.get('kind')} — {row.get('title', '')[:60]}", flush=True)
    return row


def load_backtests(limit: int = MAX_BACKTESTS) -> list[dict]:
    rows = _read_jsonl(BACKTEST_LOG)
    return list(reversed(rows[-max(1, min(limit, MAX_BACKTESTS)) :]))


def load_dev_changelog() -> list[dict]:
    if not DEV_CHANGELOG.exists():
        return []
    try:
        doc = json.loads(DEV_CHANGELOG.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = doc.get("entries") or []
    return sorted(entries, key=lambda e: e.get("at") or "", reverse=True)


def append_dev_change(
    *,
    title: str,
    summary: str,
    author: str = "Cursor agent",
    areas: list[str] | None = None,
    tags: list[str] | None = None,
) -> dict:
    _ensure_dirs()
    doc: dict[str, Any] = {"updatedAt": _now(), "entries": []}
    if DEV_CHANGELOG.exists():
        try:
            doc = json.loads(DEV_CHANGELOG.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            pass
    entry = {
        "id": str(uuid.uuid4())[:12],
        "at": _now(),
        "author": author,
        "title": title,
        "summary": summary,
        "areas": areas or [],
        "tags": tags or [],
    }
    entries = doc.get("entries") or []
    entries.insert(0, entry)
    doc["entries"] = entries[:50]
    doc["updatedAt"] = _now()
    DEV_CHANGELOG.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"[brain-journal] dev change: {title}", flush=True)
    return entry


def log_mad_scientist(doc: dict) -> dict:
    lb = doc.get("leaderboard") or []
    best = lb[0] if lb else {}
    w = doc.get("window") or {}
    return append_backtest({
        "kind": "mad_scientist_lab",
        "title": f"Mad Scientist — {doc.get('nGenomes', '?')} genomes",
        "insight": doc.get("verdict") or "Lab run completed.",
        "metrics": {
            "nGenomes": doc.get("nGenomes"),
            "nScored": doc.get("nScored"),
            "heldUp": doc.get("topSelectionHeldUp"),
            "bestHoldSharpe": best.get("holdSharpe"),
            "bestHoldReturnPct": best.get("holdReturnPct"),
            "costBps": doc.get("costBps"),
        },
        "window": w,
        "caveat": doc.get("caveat"),
        "method": doc.get("method"),
        "source": "scripts/intelligence/historical/walkforward_lab.py",
        "at": doc.get("generatedAt") or _now(),
    })


def log_fleet_walkforward(doc: dict) -> dict:
    lb = doc.get("leaderboard") or []
    best = lb[0] if lb else {}
    surv = doc.get("survivors") or []
    return append_backtest({
        "kind": "fleet_walkforward",
        "title": f"Fleet walk-forward — {doc.get('nGenomes', '?')} genomes",
        "insight": doc.get("verdict") or "Walk-forward complete.",
        "metrics": {
            "nGenomes": doc.get("nGenomes"),
            "nScored": doc.get("nScored"),
            "nSurvivors": len(surv),
            "heldUp": doc.get("topSelectionHeldUp"),
            "bestHoldSharpe": best.get("holdSharpe"),
            "bestHoldReturnPct": best.get("holdReturnPct"),
            "costBps": doc.get("costBps"),
        },
        "window": doc.get("window"),
        "caveat": doc.get("caveat"),
        "method": doc.get("method"),
        "source": "scripts/intelligence/fleet/backtest.py",
        "at": doc.get("generatedAt") or _now(),
    })


def log_investor_v3(summary: dict, *, at: str | None = None) -> dict:
    return append_backtest({
        "kind": "investor_v3",
        "title": "Investor v3 policy backtest",
        "insight": (
            f"Test-window return {summary.get('total_return_pct', 0):+.1f}% "
            f"· Sharpe {summary.get('annualized_sharpe', 0):.2f} "
            f"· {summary.get('trades', 0)} trades over {summary.get('trading_days', 0)} days."
        ),
        "metrics": {
            "returnPct": summary.get("total_return_pct"),
            "sharpe": summary.get("annualized_sharpe"),
            "maxDrawdownPct": summary.get("max_drawdown_pct"),
            "trades": summary.get("trades"),
            "winRatePct": summary.get("win_rate_pct"),
            "tradingDays": summary.get("trading_days"),
        },
        "caveat": "Investor backtest uses historical test window — forward paper is the real scoreboard.",
        "source": "scripts/train-investor-v3.py",
        "at": at or _now(),
    })


def log_harness_cycle(*, mode: str, results: dict, log_name: str | None = None) -> dict:
    ok = sum(1 for v in results.values() if v == 0)
    fail = len(results) - ok
    failed_steps = [k for k, v in results.items() if v != 0]
    return append_backtest({
        "kind": "harness_cycle",
        "title": f"Learning harness ({mode})",
        "insight": (
            f"Harness {mode} finished: {ok}/{len(results)} steps OK."
            + (f" Soft-fail: {', '.join(failed_steps[:5])}." if failed_steps else "")
        ),
        "metrics": {
            "mode": mode,
            "stepsOk": ok,
            "stepsTotal": len(results),
            "failedSteps": failed_steps[:8],
            "walkForwardRc": results.get("walk_forward"),
            "madScientistRc": results.get("mad_scientist_lab"),
            "investorRc": results.get("investor"),
        },
        "source": log_name or "scripts/learning_harness.py",
    })


def _already_logged(kind: str, at: str | None) -> bool:
    if not at:
        return False
    for row in _read_jsonl(BACKTEST_LOG):
        if row.get("kind") == kind and row.get("at") == at:
            return True
    return False


def backfill_from_artifacts() -> int:
    """Seed journal from latest artifacts if the log is sparse (no duplicates)."""
    rows = _read_jsonl(BACKTEST_LOG)
    if len(rows) >= 5:
        return 0
    added = 0
    lab = REPO / "data" / "intelligence" / "historical" / "lab_results.json"
    wf = REPO / "data" / "intelligence" / "fleet" / "walkforward.json"
    inv = REPO / "data" / "investor_v3" / "summary.json"
    for path, kind, fn in (
        (lab, "mad_scientist_lab", log_mad_scientist),
        (wf, "fleet_walkforward", log_fleet_walkforward),
    ):
        if not path.exists():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8-sig"))
            if not doc.get("ok"):
                continue
            at = doc.get("generatedAt")
            if _already_logged(kind, at):
                continue
            fn(doc)
            added += 1
        except (OSError, json.JSONDecodeError):
            pass
    if inv.exists():
        try:
            summary = json.loads(inv.read_text(encoding="utf-8-sig"))
            meta = REPO / "models" / "v3" / "investor" / "metadata.json"
            at = None
            if meta.exists():
                at = json.loads(meta.read_text(encoding="utf-8-sig")).get("trained_at")
            if not _already_logged("investor_v3", at):
                log_investor_v3(summary, at=at)
                added += 1
        except (OSError, json.JSONDecodeError):
            pass
    return added


def insights_payload() -> dict:
    backfill_from_artifacts()
    harness_path = REPO / "data" / "learning" / "harness_state.json"
    harness = {}
    if harness_path.exists():
        try:
            harness = json.loads(harness_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "ok": True,
        "generatedAt": _now(),
        "backtests": load_backtests(MAX_BACKTESTS),
        "devChangelog": load_dev_changelog(),
        "harness": {
            "phase": harness.get("phase"),
            "mode": harness.get("mode"),
            "updatedAt": harness.get("updatedAt"),
            "results": harness.get("results"),
        },
    }
