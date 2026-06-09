"""
paper-agent-profit-gate.py

Profit-focused gate for the paper investing agent.

This gate does not replace model training. It evaluates the latest paper-agent
results and decides whether the strategy is healthy enough to keep current risk,
or should shift to a safer profile while data accumulates.

Outputs:
  data/paper_agent/profit-gate.json
  optionally updates data/paper_agent/agent-config.json with safer risk caps

Usage:
  python scripts/paper-agent-profit-gate.py
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = REPO_ROOT / "data" / "paper_agent"
SUMMARY_PATH = PAPER_DIR / "summary.json"
DAILY_METRICS_PATH = PAPER_DIR / "daily_metrics.csv"
CONFIG_PATH = PAPER_DIR / "agent-config.json"
OUT_PATH = PAPER_DIR / "profit-gate.json"

MIN_DAYS_FOR_HARD_GATE = int(os.getenv("PAPER_AGENT_GATE_MIN_DAYS", "25") or "25")
MIN_TRADES_FOR_HARD_GATE = int(os.getenv("PAPER_AGENT_GATE_MIN_TRADES", "120") or "120")
MIN_TOTAL_RETURN_PCT = float(os.getenv("PAPER_AGENT_GATE_MIN_TOTAL_RETURN_PCT", "0.0") or "0.0")
MAX_DRAWDOWN_PCT = float(os.getenv("PAPER_AGENT_GATE_MAX_DRAWDOWN_PCT", "9.0") or "9.0")
MIN_ONLINE_DELTA = float(os.getenv("PAPER_AGENT_GATE_MIN_ONLINE_DELTA", "-0.01") or "-0.01")
SEVERE_LOSS_TRIGGER_PCT = float(os.getenv("PAPER_AGENT_GATE_SEVERE_LOSS_TRIGGER_PCT", "-2.0") or "-2.0")
RECENT_WINDOW_DAYS = int(os.getenv("PAPER_AGENT_GATE_RECENT_WINDOW_DAYS", "20") or "20")
MIN_RECENT_RETURN_PCT = float(os.getenv("PAPER_AGENT_GATE_MIN_RECENT_RETURN_PCT", "-0.5") or "-0.5")
MAX_RECENT_DRAWDOWN_PCT = float(os.getenv("PAPER_AGENT_GATE_MAX_RECENT_DRAWDOWN_PCT", "5.0") or "5.0")


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_recent_metrics(path: Path, window_days: int) -> dict:
    if not path.exists() or window_days <= 0:
        return {
            "windowDays": 0,
            "returnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "avgDailyPnl": 0.0,
        }

    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(row)
    except Exception:
        return {
            "windowDays": 0,
            "returnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "avgDailyPnl": 0.0,
        }

    if not rows:
        return {
            "windowDays": 0,
            "returnPct": 0.0,
            "maxDrawdownPct": 0.0,
            "avgDailyPnl": 0.0,
        }

    window = rows[-window_days:]
    equities = [_safe_float(r.get("equity"), 0.0) for r in window]
    pnls = [_safe_float(r.get("daily_pnl"), 0.0) for r in window]

    start_eq = equities[0] if equities else 0.0
    end_eq = equities[-1] if equities else 0.0
    return_pct = ((end_eq / start_eq) - 1.0) * 100.0 if start_eq > 0 else 0.0

    peak = equities[0] if equities else 0.0
    max_dd = 0.0
    for eq in equities:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_dd:
                max_dd = dd

    avg_daily_pnl = sum(pnls) / len(pnls) if pnls else 0.0
    return {
        "windowDays": len(window),
        "returnPct": round(return_pct, 4),
        "maxDrawdownPct": round(max_dd * 100.0, 4),
        "avgDailyPnl": round(avg_daily_pnl, 4),
    }


def _soften_config(existing: dict) -> dict:
    out = dict(existing) if isinstance(existing, dict) else {}
    out["PAPER_AGENT_MAX_POSITIONS"] = min(int(out.get("PAPER_AGENT_MAX_POSITIONS", 8) or 8), 5)
    out["PAPER_AGENT_MIN_BUY_SCORE"] = max(0.62, _safe_float(out.get("PAPER_AGENT_MIN_BUY_SCORE", 0.54), 0.54))
    out["PAPER_AGENT_ENABLE_SHORTS"] = False
    out["PAPER_AGENT_SHORT_ALLOC_PCT"] = 0.0
    out["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"] = min(
        _safe_float(out.get("PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT", 0.85), 0.85),
        0.70,
    )
    out["PAPER_AGENT_MAX_POSITION_PCT"] = min(
        _safe_float(out.get("PAPER_AGENT_MAX_POSITION_PCT", 0.22), 0.22),
        0.16,
    )
    return out


def main() -> None:
    PAPER_DIR.mkdir(parents=True, exist_ok=True)

    summary = _load_json(SUMMARY_PATH)
    cfg = _load_json(CONFIG_PATH)

    days = int(summary.get("daysProcessed") or 0)
    trades = int(summary.get("tradeCount") or 0)
    total_return_pct = _safe_float(summary.get("totalReturnPct"), 0.0)
    max_drawdown_pct = _safe_float(summary.get("maxDrawdownPct"), 0.0)
    online_delta = _safe_float(summary.get("onlineLearningDelta"), 0.0)
    recent = _load_recent_metrics(DAILY_METRICS_PATH, RECENT_WINDOW_DAYS)

    is_hard_window = days >= MIN_DAYS_FOR_HARD_GATE and trades >= MIN_TRADES_FOR_HARD_GATE

    reasons: list[str] = []
    status = "healthy"
    needs_main_retrain = False
    softened = False

    if not summary:
        status = "insufficient_data"
        reasons.append("missing_summary")
    elif not is_hard_window:
        status = "warmup"
        reasons.append("insufficient_days_or_trades_for_hard_gate")
    else:
        if total_return_pct < MIN_TOTAL_RETURN_PCT:
            reasons.append("return_below_threshold")
        if max_drawdown_pct > MAX_DRAWDOWN_PCT:
            reasons.append("drawdown_above_threshold")
        if online_delta < MIN_ONLINE_DELTA:
            reasons.append("online_learning_delta_negative")
        if recent.get("windowDays", 0) > 0:
            if _safe_float(recent.get("returnPct"), 0.0) < MIN_RECENT_RETURN_PCT:
                reasons.append("recent_window_return_below_threshold")
            if _safe_float(recent.get("maxDrawdownPct"), 0.0) > MAX_RECENT_DRAWDOWN_PCT:
                reasons.append("recent_window_drawdown_above_threshold")

        if reasons:
            status = "degraded"
            softened_cfg = _soften_config(cfg)
            if softened_cfg != cfg:
                CONFIG_PATH.write_text(f"{json.dumps(softened_cfg, indent=2)}\n", encoding="utf-8")
                softened = True

        if total_return_pct <= SEVERE_LOSS_TRIGGER_PCT:
            needs_main_retrain = True
            if "severe_loss_trigger" not in reasons:
                reasons.append("severe_loss_trigger")

    gate_doc = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": status,
        "reasons": reasons,
        "metrics": {
            "daysProcessed": days,
            "tradeCount": trades,
            "totalReturnPct": round(total_return_pct, 4),
            "maxDrawdownPct": round(max_drawdown_pct, 4),
            "onlineLearningDelta": round(online_delta, 4),
            "recentWindow": recent,
        },
        "thresholds": {
            "minDaysForHardGate": MIN_DAYS_FOR_HARD_GATE,
            "minTradesForHardGate": MIN_TRADES_FOR_HARD_GATE,
            "minTotalReturnPct": MIN_TOTAL_RETURN_PCT,
            "maxDrawdownPct": MAX_DRAWDOWN_PCT,
            "minOnlineLearningDelta": MIN_ONLINE_DELTA,
            "severeLossTriggerPct": SEVERE_LOSS_TRIGGER_PCT,
            "recentWindowDays": RECENT_WINDOW_DAYS,
            "minRecentReturnPct": MIN_RECENT_RETURN_PCT,
            "maxRecentDrawdownPct": MAX_RECENT_DRAWDOWN_PCT,
        },
        "actions": {
            "softenedRiskConfig": softened,
            "needsMainRetrain": needs_main_retrain,
        },
    }

    OUT_PATH.write_text(f"{json.dumps(gate_doc, indent=2)}\n", encoding="utf-8")

    print("[paper-agent-profit-gate] complete")
    print(f"[paper-agent-profit-gate] status={status} reasons={','.join(reasons) if reasons else 'none'}")
    print(f"[paper-agent-profit-gate] needs_main_retrain={needs_main_retrain} softened={softened}")


if __name__ == "__main__":
    main()
