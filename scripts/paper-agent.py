"""
paper-agent.py - Online-learning paper investing agent (separate from predictor).

This script uses the existing daily prediction accuracy snapshots as its market tape.
It does NOT replace the main prediction model. Instead, it trains a second model that
learns how to allocate a simulated portfolio over time.

Core behavior:
  1) Read historical daily prediction outcomes from data/accuracy/YYYY-MM-DD.json
  2) Before each day, score candidate trades with an online SGD classifier
  3) Buy a basket at prior close (pricePrev), sell at current close (priceActual)
  4) Update the model with that day's realized outcomes (actualReturn > 0)

Default bankroll is $10,000, matching the requested fake-money setup.

Outputs:
  data/paper_agent/summary.json
  data/paper_agent/equity_curve.csv
  data/paper_agent/daily_metrics.csv
  data/paper_agent/trades.csv
  models/v2/paper_agent_model.joblib

Usage:
  python scripts/paper-agent.py
"""

from __future__ import annotations

import csv
import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import SGDClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent
ACCURACY_DIR = REPO_ROOT / "data" / "accuracy"
OUTPUT_DIR = REPO_ROOT / "data" / "paper_agent"
MODEL_PATH = REPO_ROOT / "models" / "v2" / "paper_agent_model.joblib"
AGENT_CONFIG_PATH = OUTPUT_DIR / "agent-config.json"

DEFAULT_STARTING_CASH = 10000.0
DEFAULT_MAX_POSITIONS = 8
DEFAULT_MIN_BUY_SCORE = 0.54
DEFAULT_TRADE_FEE_BPS = 2.0
DEFAULT_LOOKBACK_DAYS = 252
DEFAULT_ENABLE_SHORTS = True
DEFAULT_SHORT_ALLOC_PCT = 0.5
DEFAULT_MAX_DAILY_EXPOSURE_PCT = 0.85
DEFAULT_MAX_POSITION_PCT = 0.22
MIN_ROWS_PER_DAY = int(os.getenv("PAPER_AGENT_MIN_ROWS_PER_DAY", "50"))


def _safe_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _load_agent_config() -> dict:
    cfg = {
        "PAPER_AGENT_STARTING_CASH": DEFAULT_STARTING_CASH,
        "PAPER_AGENT_MAX_POSITIONS": DEFAULT_MAX_POSITIONS,
        "PAPER_AGENT_MIN_BUY_SCORE": DEFAULT_MIN_BUY_SCORE,
        "PAPER_AGENT_TRADE_FEE_BPS": DEFAULT_TRADE_FEE_BPS,
        "PAPER_AGENT_LOOKBACK_DAYS": DEFAULT_LOOKBACK_DAYS,
        "PAPER_AGENT_ENABLE_SHORTS": DEFAULT_ENABLE_SHORTS,
        "PAPER_AGENT_SHORT_ALLOC_PCT": DEFAULT_SHORT_ALLOC_PCT,
        "PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT": DEFAULT_MAX_DAILY_EXPOSURE_PCT,
        "PAPER_AGENT_MAX_POSITION_PCT": DEFAULT_MAX_POSITION_PCT,
    }

    if AGENT_CONFIG_PATH.exists():
        try:
            from_file = json.loads(AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(from_file, dict):
                cfg.update(from_file)
        except Exception:
            pass

    # Environment wins over tuned-file values.
    cfg["PAPER_AGENT_STARTING_CASH"] = _safe_float(
        os.getenv("PAPER_AGENT_STARTING_CASH", cfg["PAPER_AGENT_STARTING_CASH"]),
        cfg["PAPER_AGENT_STARTING_CASH"],
    )
    cfg["PAPER_AGENT_MAX_POSITIONS"] = _safe_int(
        os.getenv("PAPER_AGENT_MAX_POSITIONS", cfg["PAPER_AGENT_MAX_POSITIONS"]),
        int(cfg["PAPER_AGENT_MAX_POSITIONS"]),
    )
    cfg["PAPER_AGENT_MIN_BUY_SCORE"] = _safe_float(
        os.getenv("PAPER_AGENT_MIN_BUY_SCORE", cfg["PAPER_AGENT_MIN_BUY_SCORE"]),
        cfg["PAPER_AGENT_MIN_BUY_SCORE"],
    )
    cfg["PAPER_AGENT_TRADE_FEE_BPS"] = _safe_float(
        os.getenv("PAPER_AGENT_TRADE_FEE_BPS", cfg["PAPER_AGENT_TRADE_FEE_BPS"]),
        cfg["PAPER_AGENT_TRADE_FEE_BPS"],
    )
    cfg["PAPER_AGENT_LOOKBACK_DAYS"] = _safe_int(
        os.getenv("PAPER_AGENT_LOOKBACK_DAYS", cfg["PAPER_AGENT_LOOKBACK_DAYS"]),
        int(cfg["PAPER_AGENT_LOOKBACK_DAYS"]),
    )
    cfg["PAPER_AGENT_ENABLE_SHORTS"] = str(
        os.getenv("PAPER_AGENT_ENABLE_SHORTS", str(cfg["PAPER_AGENT_ENABLE_SHORTS"]))
    ).strip().lower() in {"1", "true", "yes", "on"}
    cfg["PAPER_AGENT_SHORT_ALLOC_PCT"] = _safe_float(
        os.getenv("PAPER_AGENT_SHORT_ALLOC_PCT", cfg["PAPER_AGENT_SHORT_ALLOC_PCT"]),
        cfg["PAPER_AGENT_SHORT_ALLOC_PCT"],
    )
    cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"] = _safe_float(
        os.getenv("PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT", cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"]),
        cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"],
    )
    cfg["PAPER_AGENT_MAX_POSITION_PCT"] = _safe_float(
        os.getenv("PAPER_AGENT_MAX_POSITION_PCT", cfg["PAPER_AGENT_MAX_POSITION_PCT"]),
        cfg["PAPER_AGENT_MAX_POSITION_PCT"],
    )
    cfg["PAPER_AGENT_SHORT_ALLOC_PCT"] = max(0.0, min(1.0, float(cfg["PAPER_AGENT_SHORT_ALLOC_PCT"])))
    cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"] = max(0.05, min(1.0, float(cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"])))
    cfg["PAPER_AGENT_MAX_POSITION_PCT"] = max(0.02, min(1.0, float(cfg["PAPER_AGENT_MAX_POSITION_PCT"])))

    return cfg


@dataclass
class DayRecord:
    date: str
    rows: list[dict]


def _safe_float(value: object, fallback: float = 0.0) -> float:
    try:
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return fallback
        return parsed
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


def _load_accuracy_days() -> list[DayRecord]:
    out: list[DayRecord] = []
    if not ACCURACY_DIR.exists():
        return out

    for path in sorted(ACCURACY_DIR.glob("*.json")):
        name = path.name
        if name in {"accuracy-log.json", "retrain-history.json"}:
            continue
        if not name[:10].count("-") == 2:
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        detail = payload.get("detail")
        if not isinstance(detail, list):
            continue

        clean_rows = []
        for row in detail:
            if not isinstance(row, dict):
                continue
            prev_price = _safe_float(row.get("pricePrev"), 0.0)
            actual_price = _safe_float(row.get("priceActual"), 0.0)
            actual_ret = _safe_float(row.get("actualReturn"), 0.0)
            ticker = str(row.get("ticker") or "").strip().upper()
            if not ticker or prev_price <= 0 or actual_price <= 0:
                continue
            clean_rows.append(
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

        if len(clean_rows) >= MIN_ROWS_PER_DAY:
            out.append(DayRecord(date=name[:10], rows=clean_rows))

    return out


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    cfg = _load_agent_config()

    starting_cash = float(cfg["PAPER_AGENT_STARTING_CASH"])
    max_positions = int(cfg["PAPER_AGENT_MAX_POSITIONS"])
    min_buy_score = float(cfg["PAPER_AGENT_MIN_BUY_SCORE"])
    trade_fee_bps = float(cfg["PAPER_AGENT_TRADE_FEE_BPS"])
    lookback_days = int(cfg["PAPER_AGENT_LOOKBACK_DAYS"])
    enable_shorts = bool(cfg["PAPER_AGENT_ENABLE_SHORTS"])
    short_alloc_pct = float(cfg["PAPER_AGENT_SHORT_ALLOC_PCT"])
    max_daily_exposure_pct = float(cfg["PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT"])
    max_position_pct = float(cfg["PAPER_AGENT_MAX_POSITION_PCT"])

    days = _load_accuracy_days()
    if lookback_days > 0 and len(days) > lookback_days:
        days = days[-lookback_days:]

    if not days:
        raise SystemExit("[paper-agent] no usable accuracy day files found")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)

    model = SGDClassifier(
        loss="log_loss",
        penalty="l2",
        alpha=0.0005,
        learning_rate="optimal",
        random_state=42,
    )
    model_ready = False

    cash = starting_cash
    equity_curve: list[dict] = []
    daily_metrics: list[dict] = []
    trades: list[dict] = []

    pre_update_hitrates: list[float] = []

    for day in days:
        rows = day.rows
        X = np.array([_feature_vector(r) for r in rows], dtype=np.float64)
        y = np.array([1 if r["actualReturn"] > 0 else 0 for r in rows], dtype=np.int32)

        if model_ready:
            scores = model.predict_proba(X)[:, 1]
        else:
            scores = np.array([r["probability"] for r in rows], dtype=np.float64)

        pre_pred = (scores >= 0.5).astype(np.int32)
        pre_day_hit = float((pre_pred == y).mean()) if len(y) > 0 else 0.0
        pre_update_hitrates.append(pre_day_hit)

        ranked_longs = sorted(
            [
                {
                    "ticker": row["ticker"],
                    "score": float(score),
                    "pricePrev": row["pricePrev"],
                    "priceActual": row["priceActual"],
                    "actualReturn": row["actualReturn"],
                    "ev": row["ev"],
                }
                for row, score in zip(rows, scores)
                if float(score) >= min_buy_score
            ],
            key=lambda item: (item["score"], item["ev"]),
            reverse=True,
        )

        ranked_shorts = []
        if enable_shorts:
            short_cutoff = 1.0 - min_buy_score
            ranked_shorts = sorted(
                [
                    {
                        "ticker": row["ticker"],
                        "score": float(score),
                        "pricePrev": row["pricePrev"],
                        "priceActual": row["priceActual"],
                        "actualReturn": row["actualReturn"],
                        "ev": row["ev"],
                    }
                    for row, score in zip(rows, scores)
                    if float(score) <= short_cutoff
                ],
                key=lambda item: (item["score"], -item["ev"]),
            )

        long_slots = max_positions
        short_slots = 0
        if enable_shorts and ranked_shorts:
            short_slots = max(1, int(round(max_positions * short_alloc_pct)))
            short_slots = min(short_slots, max_positions)
            long_slots = max(0, max_positions - short_slots)

        chosen_longs = ranked_longs[:long_slots] if long_slots > 0 else []
        chosen_shorts = ranked_shorts[:short_slots] if short_slots > 0 else []
        day_start_cash = cash
        day_notional = 0.0
        day_realized_pnl = 0.0
        day_fees = 0.0
        executed = 0

        if chosen_longs or chosen_shorts:
            deployable_cash = cash * max_daily_exposure_pct
            long_budget = deployable_cash
            short_budget = 0.0
            if chosen_longs and chosen_shorts:
                short_budget = deployable_cash * short_alloc_pct
                long_budget = deployable_cash - short_budget
            elif chosen_shorts and not chosen_longs:
                short_budget = deployable_cash
                long_budget = 0.0

            per_long_budget = (long_budget / max(1, len(chosen_longs))) if chosen_longs else 0.0
            per_short_budget = (short_budget / max(1, len(chosen_shorts))) if chosen_shorts else 0.0
            max_position_notional = cash * max_position_pct

            for pick in chosen_longs:
                buy_price = pick["pricePrev"]
                sell_price = pick["priceActual"]
                position_budget = min(per_long_budget, max_position_notional)
                qty = int(position_budget // max(0.0001, buy_price))
                if qty <= 0:
                    continue

                buy_notional = qty * buy_price
                sell_notional = qty * sell_price
                fee_buy = buy_notional * (trade_fee_bps / 10_000.0)
                fee_sell = sell_notional * (trade_fee_bps / 10_000.0)
                pnl = (sell_notional - fee_sell) - (buy_notional + fee_buy)

                cash += pnl
                day_notional += buy_notional
                day_realized_pnl += pnl
                day_fees += fee_buy + fee_sell
                executed += 1

                trades.append(
                    {
                        "date": day.date,
                        "ticker": pick["ticker"],
                        "side": "LONG",
                        "score": round(pick["score"], 6),
                        "qty": qty,
                        "buy_price": round(buy_price, 6),
                        "sell_price": round(sell_price, 6),
                        "buy_notional": round(buy_notional, 4),
                        "sell_notional": round(sell_notional, 4),
                        "fees": round(fee_buy + fee_sell, 4),
                        "pnl": round(pnl, 4),
                    }
                )

            for pick in chosen_shorts:
                short_entry = pick["pricePrev"]
                cover_price = pick["priceActual"]
                position_budget = min(per_short_budget, max_position_notional)
                qty = int(position_budget // max(0.0001, short_entry))
                if qty <= 0:
                    continue

                short_notional = qty * short_entry
                cover_notional = qty * cover_price
                fee_entry = short_notional * (trade_fee_bps / 10_000.0)
                fee_cover = cover_notional * (trade_fee_bps / 10_000.0)
                pnl = (short_notional - fee_entry) - (cover_notional + fee_cover)

                cash += pnl
                day_notional += short_notional
                day_realized_pnl += pnl
                day_fees += fee_entry + fee_cover
                executed += 1

                trades.append(
                    {
                        "date": day.date,
                        "ticker": pick["ticker"],
                        "side": "SHORT",
                        "score": round(pick["score"], 6),
                        "qty": qty,
                        "buy_price": round(short_entry, 6),
                        "sell_price": round(cover_price, 6),
                        "buy_notional": round(short_notional, 4),
                        "sell_notional": round(cover_notional, 4),
                        "fees": round(fee_entry + fee_cover, 4),
                        "pnl": round(pnl, 4),
                    }
                )

        day_return = ((cash - day_start_cash) / day_start_cash) if day_start_cash > 0 else 0.0
        equity_curve.append(
            {
                "date": day.date,
                "equity": round(cash, 4),
                "daily_pnl": round(cash - day_start_cash, 4),
                "daily_return": round(day_return, 6),
            }
        )

        daily_metrics.append(
            {
                "date": day.date,
                "rows": len(rows),
                "selected": len(chosen_longs) + len(chosen_shorts),
                "executed": executed,
                "notional": round(day_notional, 4),
                "fees": round(day_fees, 4),
                "daily_pnl": round(day_realized_pnl, 4),
                "equity": round(cash, 4),
                "pre_update_hit_rate": round(pre_day_hit, 4),
            }
        )

        # Online learning step: learn from this day's outcomes for future days.
        if not model_ready:
            model.partial_fit(X, y, classes=np.array([0, 1], dtype=np.int32))
            model_ready = True
        else:
            model.partial_fit(X, y)

    max_equity = max((row["equity"] for row in equity_curve), default=starting_cash)
    min_equity = min((row["equity"] for row in equity_curve), default=starting_cash)
    max_drawdown = (max_equity - min_equity) / max_equity if max_equity > 0 else 0.0

    head_window = pre_update_hitrates[:5] if len(pre_update_hitrates) >= 5 else pre_update_hitrates
    tail_window = pre_update_hitrates[-5:] if len(pre_update_hitrates) >= 5 else pre_update_hitrates
    head_hit = float(np.mean(head_window)) if head_window else 0.0
    tail_hit = float(np.mean(tail_window)) if tail_window else 0.0

    summary = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": "paper-agent-sgd-logistic-v1",
        "source": "data/accuracy/YYYY-MM-DD.json detail rows",
        "daysProcessed": len(days),
        "startingCash": round(starting_cash, 2),
        "finalEquity": round(cash, 2),
        "totalReturnPct": round(((cash / starting_cash) - 1.0) * 100.0, 4) if starting_cash > 0 else 0.0,
        "maxDrawdownPct": round(max_drawdown * 100.0, 4),
        "tradeCount": len(trades),
        "avgDailyPnl": round(float(np.mean([r["daily_pnl"] for r in equity_curve])) if equity_curve else 0.0, 4),
        "preUpdateHitRateEarly5": round(head_hit, 4),
        "preUpdateHitRateLate5": round(tail_hit, 4),
        "onlineLearningDelta": round(tail_hit - head_hit, 4),
        "config": {
            "PAPER_AGENT_STARTING_CASH": starting_cash,
            "PAPER_AGENT_MAX_POSITIONS": max_positions,
            "PAPER_AGENT_MIN_BUY_SCORE": min_buy_score,
            "PAPER_AGENT_TRADE_FEE_BPS": trade_fee_bps,
            "PAPER_AGENT_LOOKBACK_DAYS": lookback_days,
            "PAPER_AGENT_ENABLE_SHORTS": enable_shorts,
            "PAPER_AGENT_SHORT_ALLOC_PCT": short_alloc_pct,
            "PAPER_AGENT_MAX_DAILY_EXPOSURE_PCT": max_daily_exposure_pct,
            "PAPER_AGENT_MAX_POSITION_PCT": max_position_pct,
        },
    }

    _write_csv(
        OUTPUT_DIR / "trades.csv",
        trades,
        [
            "date",
            "ticker",
            "side",
            "score",
            "qty",
            "buy_price",
            "sell_price",
            "buy_notional",
            "sell_notional",
            "fees",
            "pnl",
        ],
    )
    _write_csv(
        OUTPUT_DIR / "equity_curve.csv",
        equity_curve,
        ["date", "equity", "daily_pnl", "daily_return"],
    )
    _write_csv(
        OUTPUT_DIR / "daily_metrics.csv",
        daily_metrics,
        [
            "date",
            "rows",
            "selected",
            "executed",
            "notional",
            "fees",
            "daily_pnl",
            "equity",
            "pre_update_hit_rate",
        ],
    )

    (OUTPUT_DIR / "summary.json").write_text(f"{json.dumps(summary, indent=2)}\n", encoding="utf-8")

    joblib.dump(
        {
            "model": model,
            "featureNames": [
                "probability",
                "confidence",
                "predictedReturn",
                "ev",
                "ensembleStd",
                "absPredictedReturn",
                "probabilityCentered",
                "probabilityTimesPredictedReturn",
                "confidenceTimesPredictedReturn",
                "evTimesConfidence",
            ],
            "trainedOnDates": [d.date for d in days],
            "trainedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        MODEL_PATH,
    )

    print("[paper-agent] complete")
    print(f"[paper-agent] days={len(days)} trades={len(trades)} final_equity={summary['finalEquity']}")
    print(f"[paper-agent] online_learning_delta={summary['onlineLearningDelta']}")


if __name__ == "__main__":
    main()
