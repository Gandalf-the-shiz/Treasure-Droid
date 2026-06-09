"""Investor v3 — fake-dollar trading agent trained on Predictor v3 outputs.

Loads test-window predictions from data/predictions_v3/test.csv (calibrated
probability + expected return for every (date, symbol)), trains a meta
HistGradientBoostingRegressor that maps {pred_proba_up, pred_ret, sector_id}
to realised next-day return, then runs a walk-forward backtest:

  - $10,000 starting cash
  - Each trading day rank symbols by (proba_up - 0.5) * predicted_ret * confidence
  - Top-K (default 20) long-only, position size via Kelly fraction capped at
    20% per name and 90% total exposure
  - Daily mark-to-market, full-turnover allowed, 5 bps round-trip costs
  - Records equity curve, trade log, Sharpe, max drawdown, win rate

Outputs:
  models/v3/investor/policy.joblib
  models/v3/investor/metadata.json
  data/investor_v3/equity_curve.csv
  data/investor_v3/trades.csv
  data/investor_v3/summary.json
"""
from __future__ import annotations
import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error

REPO = Path(__file__).resolve().parents[1]
PRED_DIR = REPO / "data" / "predictions_v3"
HIST = REPO / "data" / "historical"
OUT_MODEL = REPO / "models" / "v3" / "investor"
OUT_DATA = REPO / "data" / "investor_v3"


def kelly_fraction(p: float, b: float = 1.0) -> float:
    # Kelly for binary bet with payoff ratio b: f = p - (1 - p)/b
    f = p - (1.0 - p) / max(b, 1e-6)
    return max(0.0, min(1.0, f))


def build_liquidity_table(min_price: float, min_adv: float, min_vol_20: float, exclude_re) -> pd.DataFrame:
    """Return a dataframe of (date, symbol, close, adv_20, vol_20) for liquid bars only."""
    frames = []
    for fp in sorted(HIST.glob("*.json")):
        if fp.name in {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}:
            continue
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        stocks = data.get("stocks") or {}
        for sym, payload in stocks.items():
            if exclude_re is not None and exclude_re.match(sym):
                continue
            candles = (payload or {}).get("candles") or []
            if len(candles) < 60:
                continue
            d = pd.DataFrame(candles)
            if not {"date", "close", "volume"}.issubset(d.columns):
                continue
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d = d.dropna(subset=["date"]).sort_values("date")
            d["close"] = pd.to_numeric(d["close"], errors="coerce")
            d["volume"] = pd.to_numeric(d["volume"], errors="coerce").fillna(0)
            d["dollar_volume"] = d["close"] * d["volume"]
            d["adv_20"] = d["dollar_volume"].rolling(20).mean()
            d["vol_20"] = d["close"].pct_change().rolling(20).std()
            d = d[(d["close"] >= min_price) & (d["adv_20"] >= min_adv) & (d["vol_20"] >= min_vol_20)]
            if d.empty:
                continue
            d = d[["date", "close", "adv_20", "vol_20"]].copy()
            d["symbol"] = sym
            frames.append(d)
    if not frames:
        raise SystemExit("no liquid bars found")
    out = pd.concat(frames, ignore_index=True)
    print(f"[liquidity] kept {len(out):,} (date,symbol) bars across {out['symbol'].nunique()} symbols", flush=True)
    return out


def build_price_history(start_date: pd.Timestamp, exclude_re) -> dict[str, pd.DataFrame]:
    """Return {symbol: DataFrame(date, open, high, low, close, volume)} for use in 30-day
    lookback charts. Filters only by exclude regex + min candles; keeps bars within the
    test window (with 60-trading-day lookback buffer)."""
    cutoff = (start_date - pd.Timedelta(days=120)).normalize()
    out: dict[str, pd.DataFrame] = {}
    for fp in sorted(HIST.glob("*.json")):
        if fp.name in {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}:
            continue
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        stocks = data.get("stocks") or {}
        for sym, payload in stocks.items():
            if exclude_re is not None and exclude_re.match(sym):
                continue
            candles = (payload or {}).get("candles") or []
            if len(candles) < 60:
                continue
            d = pd.DataFrame(candles)
            if "date" not in d.columns or "close" not in d.columns:
                continue
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
            d = d.dropna(subset=["date"]).sort_values("date")
            d = d[d["date"] >= cutoff]
            if d.empty:
                continue
            for c in ("open", "high", "low", "close", "volume"):
                if c in d.columns:
                    d[c] = pd.to_numeric(d[c], errors="coerce")
            out[sym] = d.reset_index(drop=True)
    print(f"[price-history] loaded {len(out):,} symbols", flush=True)
    return out


def _why_text(row: dict, rank: int) -> list[str]:
    """Produce a short, human-readable bullet list explaining why this pick was chosen."""
    p = float(row["pred_proba_up"]); pr = float(row["pred_ret"])
    edge = float(row.get("edge", (2*p - 1) * abs(pr)))
    sec = str(row.get("sector") or "unknown")
    vol20 = float(row.get("vol_20", 0.0))
    bullets = [
        f"Calibrated up-day probability {p*100:.1f}% (threshold 60%) \u2014 model is confident this name rises tomorrow.",
        f"Predicted next-day return {pr*100:+.2f}% (floor 2.0%) \u2014 expected magnitude clears the {2*5+2*10} bps cost+slippage drag.",
        f"Edge score {edge*100:+.3f}% ranks #{rank} across today's eligible universe after liquidity, vol and exclusion filters.",
        f"Sector: {sec}. 20d realised daily vol {vol20*100:.2f}% (floor 1.0%) \u2014 enough movement for the predicted edge to materialise.",
    ]
    return bullets


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--starting-cash", type=float, default=10_000.0)
    ap.add_argument("--top-k", type=int, default=20)
    ap.add_argument("--max-position-frac", type=float, default=0.20)
    ap.add_argument("--max-gross-exposure", type=float, default=0.90)
    ap.add_argument("--kelly-scale", type=float, default=0.5, help="fractional-Kelly multiplier")
    ap.add_argument("--cost-bps", type=float, default=5.0, help="round-trip transaction cost in basis points")
    ap.add_argument("--min-proba", type=float, default=0.52, help="skip signals below this proba")
    ap.add_argument("--min-price", type=float, default=5.0, help="liquidity filter: min close price")
    ap.add_argument("--min-adv", type=float, default=1_000_000.0, help="liquidity filter: min 20d avg $ volume")
    ap.add_argument("--slippage-bps", type=float, default=10.0, help="per-side slippage in bps applied to realised return")
    ap.add_argument("--max-daily-ret", type=float, default=0.20, help="cap on per-trade realised return (sanity guardrail)")
    ap.add_argument("--policy-mode", choices=["regressor", "edge", "proba"], default="edge",
                    help="ranking signal: regressor=HGBR meta-model, edge=(2p-1)*|pred_ret|, proba=p")
    ap.add_argument("--min-pred-ret", type=float, default=0.005,
                    help="require predicted return above this (excludes cash-equivalent ETFs)")
    ap.add_argument("--min-vol-20", type=float, default=0.01,
                    help="require 20d realised daily vol above this (excludes treasury/cash ETFs)")
    ap.add_argument("--exclude-pattern", type=str, default="^(BIL|TBIL|TBLL|BILS|BILZ|GBIL|SGOV|USFR|VUSB|XHLF|CLIP|GSY|ZVZZT|ZVV|ZWZZT|ZXIET|ZXZZT|NTEST)",
                    help="regex of symbols to exclude")
    args = ap.parse_args()

    OUT_MODEL.mkdir(parents=True, exist_ok=True)
    OUT_DATA.mkdir(parents=True, exist_ok=True)

    val_path = PRED_DIR / "val.csv"
    test_path = PRED_DIR / "test.csv"
    if not val_path.exists() or not test_path.exists():
        raise SystemExit(f"missing predictor outputs at {PRED_DIR}; run train-predictor-v3.py first")
    val = pd.read_csv(val_path, parse_dates=["date"])
    test = pd.read_csv(test_path, parse_dates=["date"])
    print(f"[load] val={len(val):,} test={len(test):,} test_dates={test['date'].nunique()} symbols={test['symbol'].nunique()}", flush=True)

    import re as _re
    exclude_re = _re.compile(args.exclude_pattern) if args.exclude_pattern else None
    liq = build_liquidity_table(args.min_price, args.min_adv, args.min_vol_20, exclude_re)
    before_v, before_t = len(val), len(test)
    val = val.merge(liq, on=["date", "symbol"], how="inner")
    test = test.merge(liq, on=["date", "symbol"], how="inner")
    val = val[val["pred_ret"] >= args.min_pred_ret]
    test = test[test["pred_ret"] >= args.min_pred_ret]
    print(f"[liquidity-filter] val {before_v:,} -> {len(val):,}  test {before_t:,} -> {len(test):,}", flush=True)

    # Encode sector as ordinal id
    sectors = sorted(pd.concat([val["sector"], test["sector"]]).dropna().unique().tolist())
    sec_id = {s: i for i, s in enumerate(sectors)}
    for d in (val, test):
        d["sector_id"] = d["sector"].map(sec_id).fillna(-1).astype(int)
        d["edge"] = (d["pred_proba_up"] - 0.5) * 2.0 * d["pred_ret"]
        d["confidence"] = (d["pred_proba_up"] - 0.5).abs() * 2.0

    try:
        from overlay_features import attach_congress_features, attach_insider_features

        for d in (val, test):
            attach_congress_features(d, date_col="date")
            attach_insider_features(d, date_col="date")
    except Exception as exc:
        print(f"[overlay] congress/insider attach skipped: {exc}", flush=True)

    overlay_cols = ["congress_score", "congress_net_score", "insider_cluster_score", "insider_ceo_buy_flag"]
    for d in (val, test):
        for c in overlay_cols:
            if c not in d.columns:
                d[c] = 0.0

    feat_cols = ["pred_proba_up", "pred_ret", "sector_id", "edge", "confidence"] + overlay_cols
    # Train policy regressor on VAL: features -> realised next-day return
    policy = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.05,
        max_iter=300,
        max_depth=6,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=25,
        random_state=0,
    )
    Xv = val[feat_cols].to_numpy(dtype=np.float32)
    yv = val["y_ret"].to_numpy(dtype=np.float32)
    policy.fit(Xv, yv)
    test["policy_score_regressor"] = policy.predict(test[feat_cols].to_numpy(dtype=np.float32))
    test["policy_score_edge"] = (2.0 * test["pred_proba_up"] - 1.0) * test["pred_ret"].abs()
    test["policy_score_proba"] = test["pred_proba_up"]
    test["policy_score"] = test[f"policy_score_{args.policy_mode}"]

    # Optional: boost ranking when politicians (e.g. Pelosi) are buying the same symbol.
    #
    # LEAKAGE GUARD: load_signals() returns the *current* congress snapshot keyed by
    # symbol only (no as-of date). Applying it to historical backtest rows leaks the
    # future into the past and inflates backtest returns. It is therefore DISABLED by
    # default for the backtest and must stay off until point-in-time congress signals
    # (scored per backtest date from filing_date) are wired in. Live/forward ranking
    # may opt in via CONGRESS_BOOST_ENABLED=true, but never trust a boosted backtest.
    congress_boost = os.getenv("CONGRESS_BOOST_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    if congress_boost:
        print("[congress] WARNING: boost enabled — current signals on historical rows "
              "is look-ahead; backtest metrics are not trustworthy with this on.", flush=True)
        try:
            from congress_signals import load_signals

            sigs = load_signals()
            if sigs:
                def _cscore(sym: object) -> float:
                    s = sigs.get(str(sym).upper()) or {}
                    return float(s.get("congress_score") or 0.0)

                test["congress_score"] = test["symbol"].map(_cscore)
                test["policy_score"] = test["policy_score"] * (
                    1.0 + test["congress_score"].clip(0.0, 1.0) * float(os.getenv("CONGRESS_POLICY_WEIGHT", "0.12"))
                )
                pel_extra = float(os.getenv("CONGRESS_PELOSI_EXTRA", "0.05"))
                pel_mask = test["symbol"].map(
                    lambda s: bool((sigs.get(str(s).upper()) or {}).get("pelosi_buy"))
                )
                test.loc[pel_mask, "policy_score"] *= 1.0 + pel_extra
                print(f"[congress] boosted policy_score for {int(pel_mask.sum())} Pelosi-flagged rows", flush=True)
        except Exception as exc:
            print(f"[congress] boost skipped: {exc}", flush=True)

    joblib.dump(policy, OUT_MODEL / "policy.joblib")
    print(f"[policy] mode={args.policy_mode} iters={policy.n_iter_} val_mae={mean_absolute_error(yv, policy.predict(Xv)):.5f}", flush=True)
    # Also export to ONNX (portable; usable in browser via onnxruntime-web or on
    # the Snapdragon NPU via the QNN execution provider). Soft-fail if skl2onnx
    # is not installed — pickle is still the source of truth.
    try:
        from skl2onnx import convert_sklearn  # type: ignore
        from skl2onnx.common.data_types import FloatTensorType  # type: ignore
        import onnx.helper as _onnx_helper  # type: ignore

        if not getattr(_onnx_helper, "_nostra_patched", False):
            _orig_make_attr = _onnx_helper.make_attribute
            def _coerce_bool_attr(*a, **kw):
                if len(a) >= 2:
                    key, value, rest = a[0], a[1], a[2:]
                else:
                    key = kw.get("key"); value = kw.pop("value", None); rest = ()
                if value is not None and not isinstance(value, (str, bytes, int, float)):
                    try:
                        seq = list(value)
                        if seq and any(isinstance(v, bool) for v in seq):
                            value = [int(v) if isinstance(v, bool) else v for v in seq]
                    except TypeError:
                        pass
                return _orig_make_attr(key, value, *rest, **kw)
            _onnx_helper.make_attribute = _coerce_bool_attr
            _onnx_helper._nostra_patched = True

        onnx_model = convert_sklearn(
            policy,
            initial_types=[("float_input", FloatTensorType([None, len(feat_cols)]))],
            target_opset=18,
        )
        onnx_path = OUT_MODEL / "policy.onnx"
        onnx_path.write_bytes(onnx_model.SerializeToString())
        (OUT_MODEL / "policy.onnx.meta.json").write_text(json.dumps({
            "input_name": "float_input",
            "input_shape": ["batch", len(feat_cols)],
            "dtype": "float32",
            "feature_order": feat_cols,
            "model_class": type(policy).__name__,
        }, indent=2))
        print(f"[policy] exported ONNX → {onnx_path.relative_to(Path.cwd()) if onnx_path.is_relative_to(Path.cwd()) else onnx_path} ({onnx_path.stat().st_size/1024:.1f} KiB)", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[policy] ONNX export skipped: {e}", flush=True)

    # ----- Backtest on test window -----
    test = test.sort_values(["date", "policy_score"], ascending=[True, False]).reset_index(drop=True)
    # Per-day rank used for reasoning text
    test["rank_today"] = test.groupby("date")["policy_score"].rank(ascending=False, method="first").astype(int)
    cash = float(args.starting_cash)
    equity_curve = []
    trade_log = []
    decisions_days = []  # rich per-day log for UI
    held: dict[str, dict] = {}  # symbol -> {'shares': n, 'entry_price': p, 'entry_date': d}
    cost_rate = args.cost_bps / 1e4
    slip_rate = args.slippage_bps / 1e4
    ret_cap = args.max_daily_ret

    dates = sorted(test["date"].unique())
    print(f"[backtest] {len(dates)} trading days, $%.2f start" % args.starting_cash, flush=True)
    for di, day in enumerate(dates):
        day_df = test[test["date"] == day]
        # Eligible: proba above threshold AND policy_score > 0
        eligible = day_df[(day_df["pred_proba_up"] >= args.min_proba) & (day_df["policy_score"] > 0)]
        if eligible.empty:
            picks = eligible
        else:
            picks = eligible.head(args.top_k)

        # 1) Settle yesterday's positions: we paid `notional` to enter, get back notional*(1+r) minus costs
        pnl_today = 0.0
        settled_today: dict[str, dict] = {}
        for sym, pos in list(held.items()):
            r = pos["next_ret"]
            # Realism: bound per-trade realised return (outliers in Stooq data),
            # subtract slippage on both legs and round-trip transaction cost.
            r = max(-ret_cap, min(ret_cap, r))
            r_net = r - 2.0 * slip_rate
            proceeds = pos["notional"] * (1.0 + r_net)
            cost = pos["notional"] * cost_rate
            pnl = proceeds - pos["notional"] - cost
            cash += proceeds - cost
            pnl_today += pnl
            trade_log.append({
                "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
                "exit_date": day.strftime("%Y-%m-%d"),
                "symbol": sym,
                "notional": pos["notional"],
                "ret": r,
                "ret_net": r_net,
                "pnl": pnl,
            })
            settled_today[sym] = {"ret": r, "ret_net": r_net, "pnl": pnl}
        held.clear()

        # 2) Open today's bets, sized off available cash
        equity_before_new = cash
        budget = equity_before_new * args.max_gross_exposure
        day_picks_record: list[dict] = []
        if not picks.empty and budget > 0:
            weights = []
            for _, row in picks.iterrows():
                pay = max(abs(float(row["pred_ret"])), 0.005)
                k = kelly_fraction(float(row["pred_proba_up"]), b=1.0) * args.kelly_scale
                w = k * (1.0 + min(2.0, pay * 50))
                weights.append(w)
            weights = np.array(weights, dtype=np.float64)
            if weights.sum() <= 0:
                weights[:] = 1.0
            weights = weights / weights.sum()

            for (_, row), w in zip(picks.iterrows(), weights):
                cap = equity_before_new * args.max_position_frac
                notional = min(cap, budget * w)
                if notional < 50:
                    continue
                if notional > cash:
                    notional = cash
                if notional < 50:
                    continue
                cash -= notional
                held[row["symbol"]] = {
                    "entry_date": day,
                    "notional": notional,
                    "next_ret": float(row["y_ret"]),
                }
                day_picks_record.append({
                    "symbol": str(row["symbol"]),
                    "sector": str(row.get("sector") or "unknown"),
                    "rank": int(row["rank_today"]),
                    "notional": float(notional),
                    "weight": float(notional / max(equity_before_new, 1e-9)),
                    "entry_price": float(row["close"]),
                    "pred_proba_up": float(row["pred_proba_up"]),
                    "pred_ret": float(row["pred_ret"]),
                    "edge": float(row["edge"]),
                    "confidence": float(row["confidence"]),
                    "vol_20": float(row["vol_20"]),
                    "adv_20": float(row["adv_20"]),
                    "policy_score": float(row["policy_score"]),
                    "realised_ret": float(row["y_ret"]),
                    "realised_up": int(row["y_up"]) if "y_up" in row else None,
                    "why": _why_text(row.to_dict(), int(row["rank_today"])),
                })
        equity = cash + sum(p["notional"] for p in held.values())
        equity_curve.append({"date": day.strftime("%Y-%m-%d"), "equity": equity, "cash": cash, "positions": len(held), "picks": int(len(picks))})
        decisions_days.append({
            "date": day.strftime("%Y-%m-%d"),
            "equity": float(equity),
            "cash": float(cash),
            "pnl_today": float(pnl_today),
            "eligible_count": int(len(eligible)),
            "picks": day_picks_record,
            "settled": [{"symbol": s, **v} for s, v in settled_today.items()],
        })

        if di % 50 == 0 or di == len(dates) - 1:
            print(f"[bt] {day.date()} equity=${equity:,.2f} cash=${cash:,.2f} positions={len(held)}", flush=True)

    # Close any final positions at their stored next_ret (last bet realises one more day)
    for sym, pos in list(held.items()):
        r = pos["next_ret"]
        r = max(-ret_cap, min(ret_cap, r))
        r_net = r - 2.0 * slip_rate
        proceeds = pos["notional"] * (1.0 + r_net)
        cost = pos["notional"] * cost_rate
        cash += proceeds - cost
        trade_log.append({
            "entry_date": pos["entry_date"].strftime("%Y-%m-%d"),
            "exit_date": "FINAL",
            "symbol": sym,
            "notional": pos["notional"],
            "ret": r,
            "ret_net": r_net,
            "pnl": proceeds - pos["notional"] - cost,
        })
    equity_curve.append({"date": "FINAL", "equity": cash, "cash": cash, "positions": 0, "picks": 0})

    eq_df = pd.DataFrame(equity_curve)
    tr_df = pd.DataFrame(trade_log)
    eq_df.to_csv(OUT_DATA / "equity_curve.csv", index=False)
    tr_df.to_csv(OUT_DATA / "trades.csv", index=False)

    # Stats
    equities = eq_df["equity"].to_numpy(dtype=np.float64)
    returns = np.diff(equities) / equities[:-1]
    sharpe = float(returns.mean() / returns.std() * math.sqrt(252)) if returns.std() > 0 else 0.0
    peak = np.maximum.accumulate(equities)
    drawdown = (equities - peak) / peak
    max_dd = float(drawdown.min())
    wins = int((tr_df["pnl"] > 0).sum()) if len(tr_df) else 0
    losses = int((tr_df["pnl"] <= 0).sum()) if len(tr_df) else 0
    win_rate = float(wins / max(1, wins + losses))
    total_return = float(cash / args.starting_cash - 1.0)
    summary = {
        "starting_cash": args.starting_cash,
        "ending_cash": float(cash),
        "total_return_pct": total_return * 100,
        "annualized_sharpe": sharpe,
        "max_drawdown_pct": max_dd * 100,
        "trading_days": int(len(dates)),
        "trades": int(len(tr_df)),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate * 100,
        "config": {
            "top_k": args.top_k,
            "max_position_frac": args.max_position_frac,
            "max_gross_exposure": args.max_gross_exposure,
            "kelly_scale": args.kelly_scale,
            "cost_bps": args.cost_bps,
            "min_proba": args.min_proba,
        },
    }
    with open(OUT_DATA / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    metadata = {
        "version": "3.0.0-investor-v3",
        "trained_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "architecture": "HistGradientBoostingRegressor policy + fractional-Kelly long-only allocator",
        "feature_columns": feat_cols,
        "summary": summary,
    }
    with open(OUT_MODEL / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # ---- Rich decisions.json for the in-browser Investor tab ----
    test_start = pd.Timestamp(dates[0])
    price_hist = build_price_history(test_start, exclude_re)
    needed_syms = {p["symbol"] for d in decisions_days for p in d["picks"]}
    history_payload: dict[str, list[dict]] = {}
    for sym in needed_syms:
        df = price_hist.get(sym)
        if df is None:
            continue
        rows = df.tail(400)
        history_payload[sym] = [
            {
                "date": r["date"].strftime("%Y-%m-%d"),
                "open": None if pd.isna(r.get("open")) else float(r["open"]),
                "high": None if pd.isna(r.get("high")) else float(r["high"]),
                "low": None if pd.isna(r.get("low")) else float(r["low"]),
                "close": None if pd.isna(r.get("close")) else float(r["close"]),
                "volume": None if pd.isna(r.get("volume")) else float(r["volume"]),
            }
            for _, r in rows.iterrows()
        ]

    decisions = {
        "version": metadata["version"],
        "generated_at": metadata["trained_at"],
        "summary": summary,
        "config": summary["config"] | {
            "min_pred_ret": args.min_pred_ret,
            "min_vol_20": args.min_vol_20,
            "slippage_bps": args.slippage_bps,
            "max_daily_ret": args.max_daily_ret,
            "policy_mode": args.policy_mode,
            "exclude_pattern": args.exclude_pattern,
        },
        "feature_columns": feat_cols,
        "sectors": sectors,
        "equity_curve": [
            {"date": e["date"], "equity": float(e["equity"]), "cash": float(e["cash"]),
             "positions": int(e["positions"]), "picks": int(e["picks"])}
            for e in equity_curve if e["date"] != "FINAL"
        ],
        "days": decisions_days,
        "price_history": history_payload,
    }
    with open(OUT_DATA / "decisions.json", "w", encoding="utf-8") as f:
        json.dump(decisions, f, separators=(",", ":"))
    print(f"[decisions] wrote {OUT_DATA / 'decisions.json'} ({len(decisions_days)} days, {len(needed_syms)} unique symbols)", flush=True)

    print("\n=== INVESTOR SUMMARY ===")
    print(json.dumps(summary, indent=2))
    try:
        from intelligence.brain.journal import log_investor_v3
        log_investor_v3(summary)
    except Exception as exc:
        print(f"[brain-journal] skip investor log: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
