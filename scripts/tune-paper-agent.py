"""
tune-paper-agent.py - Grid-search tuner for the online paper investing agent.

Uses the same daily accuracy detail rows as paper-agent.py and evaluates
configuration candidates by final simulated equity over the selected lookback.

Outputs:
  data/paper_agent/tuner-latest.json
  data/paper_agent/agent-config.json

Usage:
  python scripts/tune-paper-agent.py
"""

from __future__ import annotations

import itertools
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import SGDClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent
ACCURACY_DIR = REPO_ROOT / "data" / "accuracy"
OUT_DIR = REPO_ROOT / "data" / "paper_agent"

LOOKBACK_DAYS = 252
STARTING_CASH = 10000.0
MIN_TRADES_FOR_VALID_TRIAL = int(os.getenv("PAPER_AGENT_MIN_TRADES_FOR_VALID_TRIAL", "30") or "30")


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        v = float(value)
        if np.isnan(v) or np.isinf(v):
            return fallback
        return v
    except Exception:
        return fallback


def _feature_vector(row: dict) -> list[float]:
    prob = _safe_float(row.get("probability"), 0.5)
    conf = _safe_float(row.get("confidence"), 0.0)
    pred_ret = _safe_float(row.get("predictedReturn"), 0.0)
    ev = _safe_float(row.get("ev"), 0.0)
    estd = _safe_float(row.get("ensembleStd"), 0.0)

    return [
        prob,
        conf,
        pred_ret,
        ev,
        estd,
        abs(pred_ret),
        prob - 0.5,
        pred_ret * prob,
        pred_ret * conf,
        ev * conf,
    ]


def load_days() -> list[dict]:
    days: list[dict] = []

    for path in sorted(ACCURACY_DIR.glob("*.json")):
        if path.name in {"accuracy-log.json", "retrain-history.json"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        detail = payload.get("detail")
        if not isinstance(detail, list):
            continue

        rows = []
        for row in detail:
            prev_price = _safe_float(row.get("pricePrev"), 0.0)
            actual_price = _safe_float(row.get("priceActual"), 0.0)
            actual_ret = _safe_float(row.get("actualReturn"), 0.0)
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker or prev_price <= 0 or actual_price <= 0:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "pricePrev": prev_price,
                    "priceActual": actual_price,
                    "actualReturn": actual_ret,
                    "probability": _safe_float(row.get("probability"), 0.5),
                    "confidence": _safe_float(row.get("confidence"), 0.0),
                    "predictedReturn": _safe_float(row.get("predictedReturn"), 0.0),
                    "ev": _safe_float(row.get("ev"), 0.0),
                    "ensembleStd": _safe_float(row.get("ensembleStd"), 0.0),
                }
            )

        if len(rows) >= 50:
            days.append({"date": path.stem[:10], "rows": rows})

    if LOOKBACK_DAYS > 0 and len(days) > LOOKBACK_DAYS:
        days = days[-LOOKBACK_DAYS:]

    return days


def simulate(
    days: list[dict],
    min_buy_score: float,
    max_positions: int,
    fee_bps: float,
    enable_shorts: bool,
    short_alloc_pct: float,
) -> dict:
    model = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=0.0005,
        learning_rate="optimal",
        random_state=42,
    )
    model_ready = False

    cash = STARTING_CASH
    total_trades = 0
    hit_rates = []
    daily_returns = []
    equity_series = [STARTING_CASH]

    for day in days:
        day_start_cash = cash
        rows = day["rows"]
        X = np.array([_feature_vector(r) for r in rows], dtype=np.float64)
        y = np.array([1 if r["actualReturn"] > 0 else 0 for r in rows], dtype=np.int32)

        if model_ready:
            scores = model.predict_proba(X)[:, 1]
        else:
            scores = np.array([r["probability"] for r in rows], dtype=np.float64)

        pred = (scores >= 0.5).astype(np.int32)
        hit_rates.append(float((pred == y).mean()))

        ranked_longs = sorted(
            [
                {
                    "score": float(score),
                    "pricePrev": row["pricePrev"],
                    "priceActual": row["priceActual"],
                    "ev": row["ev"],
                }
                for row, score in zip(rows, scores)
                if float(score) >= min_buy_score
            ],
            key=lambda item: (item["score"], item["ev"]),
            reverse=True,
        )

        ranked_shorts = []
        short_slots = 0
        long_slots = max_positions
        if enable_shorts:
            short_cutoff = 1.0 - min_buy_score
            ranked_shorts = sorted(
                [
                    {
                        "score": float(score),
                        "pricePrev": row["pricePrev"],
                        "priceActual": row["priceActual"],
                        "ev": row["ev"],
                    }
                    for row, score in zip(rows, scores)
                    if float(score) <= short_cutoff
                ],
                key=lambda item: (item["score"], -item["ev"]),
            )
            short_slots = max(1, int(round(max_positions * short_alloc_pct)))
            short_slots = min(short_slots, max_positions)
            long_slots = max(0, max_positions - short_slots)

        chosen_longs = ranked_longs[:long_slots]
        chosen_shorts = ranked_shorts[:short_slots]

        if chosen_longs or chosen_shorts:
            short_budget = cash * short_alloc_pct if chosen_shorts else 0.0
            long_budget = cash - short_budget if chosen_longs else 0.0

            if chosen_longs:
                budget = long_budget / max(1, len(chosen_longs))
            else:
                budget = 0.0
            for pick in chosen_longs:
                qty = int(budget // max(0.0001, pick["pricePrev"]))
                if qty <= 0:
                    continue
                buy_notional = qty * pick["pricePrev"]
                sell_notional = qty * pick["priceActual"]
                fee_buy = buy_notional * (fee_bps / 10_000.0)
                fee_sell = sell_notional * (fee_bps / 10_000.0)
                pnl = (sell_notional - fee_sell) - (buy_notional + fee_buy)
                cash += pnl
                total_trades += 1

            if chosen_shorts:
                short_budget_each = short_budget / max(1, len(chosen_shorts))
            else:
                short_budget_each = 0.0
            for pick in chosen_shorts:
                qty = int(short_budget_each // max(0.0001, pick["pricePrev"]))
                if qty <= 0:
                    continue
                short_notional = qty * pick["pricePrev"]
                cover_notional = qty * pick["priceActual"]
                fee_entry = short_notional * (fee_bps / 10_000.0)
                fee_cover = cover_notional * (fee_bps / 10_000.0)
                pnl = (short_notional - fee_entry) - (cover_notional + fee_cover)
                cash += pnl
                total_trades += 1

        if not model_ready:
            model.partial_fit(X, y, classes=np.array([0, 1], dtype=np.int32))
            model_ready = True
        else:
            model.partial_fit(X, y)

        if day_start_cash > 0:
            daily_returns.append((cash - day_start_cash) / day_start_cash)
        equity_series.append(cash)

    peak = equity_series[0] if equity_series else STARTING_CASH
    max_drawdown = 0.0
    for eq in equity_series:
        if eq > peak:
            peak = eq
        if peak > 0:
            dd = (peak - eq) / peak
            if dd > max_drawdown:
                max_drawdown = dd

    avg_daily = float(np.mean(daily_returns)) if daily_returns else 0.0
    vol_daily = float(np.std(daily_returns)) if daily_returns else 0.0
    sharpe_like = (avg_daily / vol_daily) if vol_daily > 0 else 0.0

    return_pct = ((cash / STARTING_CASH) - 1.0) * 100.0
    trade_penalty = 0.0
    if total_trades < MIN_TRADES_FOR_VALID_TRIAL:
        trade_penalty = float((MIN_TRADES_FOR_VALID_TRIAL - total_trades) * 0.2)

    objective_score = (
        return_pct
        + (6.0 * sharpe_like)
        - (0.9 * (max_drawdown * 100.0))
        + (2.0 * (float(np.mean(hit_rates)) if hit_rates else 0.0))
        - trade_penalty
    )

    return {
        "finalEquity": round(float(cash), 2),
        "returnPct": round(return_pct, 4),
        "tradeCount": total_trades,
        "avgHitRate": round(float(np.mean(hit_rates)) if hit_rates else 0.0, 4),
        "maxDrawdownPct": round(max_drawdown * 100.0, 4),
        "sharpeLike": round(sharpe_like, 6),
        "objectiveScore": round(objective_score, 6),
        "days": len(days),
    }


def main() -> None:
    days = load_days()
    if not days:
        raise SystemExit("[tune-paper-agent] no usable day files")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    min_score_grid = [0.50, 0.54, 0.58, 0.62, 0.66, 0.70]
    max_positions_grid = [3, 5, 8, 12]
    fee_grid = [1.0, 2.0, 3.0]
    enable_shorts_grid = [False, True]
    short_alloc_grid = [0.25, 0.4, 0.5, 0.65, 0.8]

    trials = []
    for min_score, max_pos, fee, enable_shorts, short_alloc in itertools.product(
        min_score_grid,
        max_positions_grid,
        fee_grid,
        enable_shorts_grid,
        short_alloc_grid,
    ):
        if not enable_shorts and short_alloc != short_alloc_grid[0]:
            continue

        effective_short_alloc = short_alloc if enable_shorts else 0.0
        outcome = simulate(days, min_score, max_pos, fee, enable_shorts, effective_short_alloc)
        trials.append(
            {
                "config": {
                    "PAPER_AGENT_STARTING_CASH": STARTING_CASH,
                    "PAPER_AGENT_LOOKBACK_DAYS": LOOKBACK_DAYS,
                    "PAPER_AGENT_MIN_BUY_SCORE": min_score,
                    "PAPER_AGENT_MAX_POSITIONS": max_pos,
                    "PAPER_AGENT_TRADE_FEE_BPS": fee,
                    "PAPER_AGENT_ENABLE_SHORTS": enable_shorts,
                    "PAPER_AGENT_SHORT_ALLOC_PCT": effective_short_alloc,
                },
                "outcome": outcome,
            }
        )

    trials.sort(
        key=lambda t: (
            t["outcome"].get("objectiveScore", -1e18),
            t["outcome"].get("finalEquity", 0.0),
            t["outcome"].get("sharpeLike", 0.0),
            -t["outcome"].get("maxDrawdownPct", 999.0),
            t["outcome"].get("avgHitRate", 0.0),
            -t["outcome"].get("tradeCount", 0),
        ),
        reverse=True,
    )
    best = trials[0]

    report = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "daysUsed": len(days),
        "searchSpace": {
            "minBuyScore": min_score_grid,
            "maxPositions": max_positions_grid,
            "feeBps": fee_grid,
            "enableShorts": enable_shorts_grid,
            "shortAllocPct": short_alloc_grid,
            "totalTrials": len(trials),
        },
        "best": best,
        "top5": trials[:5],
    }

    (OUT_DIR / "tuner-latest.json").write_text(f"{json.dumps(report, indent=2)}\n", encoding="utf-8")
    (OUT_DIR / "agent-config.json").write_text(
        f"{json.dumps(best['config'], indent=2)}\n",
        encoding="utf-8",
    )

    print("[tune-paper-agent] complete")
    print(f"[tune-paper-agent] best_equity={best['outcome']['finalEquity']} returnPct={best['outcome']['returnPct']}")
    print(f"[tune-paper-agent] config={best['config']}")


if __name__ == "__main__":
    main()
