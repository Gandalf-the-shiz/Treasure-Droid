"""Forward-truth checks for promotion gates (Mega Yacht Phase 1.1).

Backtest promotion alone is insufficient — this module loads live readiness
and forward IC to block promotion when forward scoreboard is red.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_ROOT = Path(os.getenv("NOSTRA_LIVE_ROOT", r"C:\Users\nicho\nostradamus-live"))


def _load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def load_forward_ic() -> dict:
    for path in (
        LIVE_ROOT / "data" / "accuracy" / "v3_live_ic.json",
        REPO / "data" / "accuracy" / "v3_live_ic.json",
    ):
        doc = _load(path)
        if doc:
            return doc
    return {}


def load_readiness() -> dict:
    return _load(LIVE_ROOT / "data" / "gate" / "readiness.json")


def load_honest_eval() -> dict:
    return _load(LIVE_ROOT / "reports" / "honest_eval.json")


def forward_promotion_ok(*, require_edge_proven: bool = False) -> tuple[bool, list[str]]:
    """Return (ok, reasons). Default: block if forward paper Sharpe is sharply negative."""
    reasons: list[str] = []
    readiness = load_readiness()
    paper = readiness.get("paperSummary") or {}
    sharpe = paper.get("sharpe")
    ret = paper.get("totalReturnPct")
    marks = paper.get("nMarks") or 0

    if marks >= 20 and sharpe is not None and sharpe < -0.5:
        reasons.append(f"forward_paper_sharpe={sharpe}<-0.5")

    ic = load_forward_ic()
    n_days = ic.get("n_days") or ic.get("nDays") or 0
    mean_ic = ic.get("mean_ic") if ic.get("mean_ic") is not None else ic.get("meanRankIc")
    if n_days >= 10 and mean_ic is not None and mean_ic < 0:
        reasons.append(f"forward_ic_mean={mean_ic}<0 over {n_days}d")

    if require_edge_proven:
        ev = load_honest_eval().get("verdict") or {}
        if not ev.get("edge_proven"):
            reasons.append("honest_eval_edge_not_proven")

    return (len(reasons) == 0, reasons)


def gate_label(backtest_promoted: bool, *, strict: bool = False) -> tuple[str, list[str]]:
    """Map backtest decision + forward checks to final label."""
    if not backtest_promoted:
        return "rolled_back", ["backtest_gate_failed"]
    ok, freasons = forward_promotion_ok(require_edge_proven=strict)
    if ok:
        return "promoted", ["backtest_ok", "forward_ok"]
    return "rolled_back", ["backtest_ok"] + freasons
