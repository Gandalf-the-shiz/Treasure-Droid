"""Penny Wolf — sub-$5 momentum desk (paper only).

Inspired by high-energy penny-stock *research desks* (volume, momentum, urgency) —
not illegal pump-and-dump. Everything stays paper until forward edge is proven.

Scans the local historical cache for stocks under MAX_PRICE, ranks by a heat score
(momentum + volume surge + ML tilt), maintains a separate paper book, and tracks PnL.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HIST = REPO / "data" / "historical"
LIVE_CSV = REPO / "data" / "predictions_v3" / "live.csv"
PENNY_DIR = REPO / "data" / "penny"
BOOK_PATH = PENNY_DIR / "paper_book.json"
CONFIG_PATH = PENNY_DIR / "config.json"
SCAN_PATH = PENNY_DIR / "last_scan.json"

DEFAULT_CONFIG = {
    "maxPriceUsd": 5.0,
    "minPriceUsd": 0.25,
    "minAdv20": 150_000,
    "maxPositions": 25,
    "maxPositionPct": 0.06,
    "startingCash": 100_000.0,
    "stopLossPct": 0.12,
    "takeProfitPct": 0.25,
    "topPicksPerTick": 12,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(_load_json(CONFIG_PATH, {}))
    return cfg


def load_book() -> dict:
    book = _load_json(BOOK_PATH, {})
    if not book:
        cfg = load_config()
        book = {
            "cash": cfg["startingCash"],
            "startingCash": cfg["startingCash"],
            "positions": {},
            "closedTrades": [],
            "openedAt": _now(),
        }
        _save_json(BOOK_PATH, book)
    return book


def _load_live_preds() -> dict[str, dict]:
    if not LIVE_CSV.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_csv(LIVE_CSV)
        if df.empty:
            return {}
        out = {}
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).upper()
            if sym:
                out[sym] = {
                    "pred_proba_up": float(row.get("pred_proba_up", 0.5) or 0.5),
                    "pred_ret": float(row.get("pred_ret", 0.0) or 0.0),
                }
        return out
    except Exception:
        return {}


def _candles_metrics(candles: list) -> dict | None:
    if not candles or len(candles) < 25:
        return None
    closes = [float(c.get("close", 0) or 0) for c in candles[-30:]]
    vols = [float(c.get("volume", 0) or 0) for c in candles[-30:]]
    if not closes[-1] or closes[-1] <= 0:
        return None
    px = closes[-1]
    ret_5 = (px / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else 0.0
    ret_20 = (px / closes[-20] - 1.0) if len(closes) >= 20 and closes[-20] else 0.0
    adv20 = 0.0
    for i in range(-20, 0):
        adv20 += closes[i] * vols[i]
    vol_avg = sum(vols[-20:]) / 20.0 if vols else 0.0
    vol_surge = (vols[-1] / vol_avg - 1.0) if vol_avg > 0 else 0.0
    hi, lo = max(closes[-20:]), min(closes[-20:])
    range_pct = (hi - lo) / px if px else 0.0
    return {
        "lastPx": round(px, 4),
        "ret5dPct": round(ret_5 * 100, 2),
        "ret20dPct": round(ret_20 * 100, 2),
        "adv20": round(adv20, 0),
        "volSurge": round(vol_surge, 3),
        "range20dPct": round(range_pct * 100, 2),
    }


def scan_universe(cfg: dict | None = None, limit: int = 500) -> list[dict]:
    """Return ranked penny candidates (price < maxPriceUsd)."""
    cfg = cfg or load_config()
    preds = _load_live_preds()
    max_p = float(cfg["maxPriceUsd"])
    min_p = float(cfg["minPriceUsd"])
    min_adv = float(cfg["minAdv20"])
    rows: list[dict] = []

    skip = {"manifest.json", "multiyear-coverage.json", "stooq-bulk-coverage.json"}
    for fp in sorted(HIST.glob("*.json")):
        if fp.name in skip:
            continue
        sector = fp.stem
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            candles = (payload or {}).get("candles") or []
            m = _candles_metrics(candles)
            if not m:
                continue
            px = m["lastPx"]
            if px < min_p or px >= max_p:
                continue
            if m["adv20"] < min_adv:
                continue
            pr = preds.get(sym.upper(), {})
            proba = pr.get("pred_proba_up", 0.5)
            pred_ret = pr.get("pred_ret", 0.0)
            ml_champ = _penny_champion_score(candles)
            heat = _heat_score(m, proba, pred_ret, ml_champ, sym.upper())
            row = {
                "symbol": sym.upper(),
                "sector": sector,
                "lastPx": px,
                "heat": round(heat, 2),
                "ret5dPct": m["ret5dPct"],
                "volSurge": m["volSurge"],
                "adv20": m["adv20"],
                "predProbaUp": round(proba, 4),
                "predRet": round(pred_ret, 6),
                "tag": _wolf_tag(heat, m),
            }
            if ml_champ:
                row["mlScore"] = round(ml_champ["score"], 6)
                row["mlBackend"] = ml_champ.get("backend")
            rows.append(row)

    rows.sort(key=lambda r: r["heat"], reverse=True)
    top = rows[:limit]
    _save_json(SCAN_PATH, {"generatedAt": _now(), "count": len(rows), "top": top[:50]})
    return top


def _penny_champion_score(candles: list) -> dict | None:
    try:
        from penny_ml.score_live import score_candles
        return score_candles(candles)
    except Exception:
        return None


def _heat_score(
    m: dict,
    proba: float,
    pred_ret: float,
    ml_champ: dict | None = None,
    symbol: str = "",
) -> float:
    """0–100 'desk heat' — momentum + volume + unified intelligence + penny ML."""
    mom = max(-20, min(20, m["ret5dPct"])) / 20.0
    vol = max(0, min(3, m["volSurge"])) / 3.0
    penny_ml = float(ml_champ["score"]) if ml_champ and ml_champ.get("score") is not None else None
    intel_bonus = 0.0
    if symbol:
        try:
            from intelligence.unified_score import composite_score, load_unified_config
            if load_unified_config().get("enabled"):
                sc = composite_score(
                    symbol,
                    pred_proba_up=proba,
                    pred_ret=pred_ret,
                    side="long",
                    alt_scale=1.0,
                    penny_ml_score=penny_ml,
                )
                intel_bonus = max(-0.25, min(0.35, float(sc["composite"]) * 0.08))
        except Exception:
            pass
    ml = (proba - 0.5) * 2.0 + pred_ret * 50.0
    if penny_ml is not None:
        ml = max(-1.0, min(1.0, penny_ml * 20.0))
    raw = 35 * mom + 30 * vol + 20 * max(-1, min(1, ml)) + 15 * min(1.0, m["range20dPct"] / 40.0)
    raw += intel_bonus * 100
    return max(0.0, min(100.0, 50 + raw * 25))


def _wolf_tag(heat: float, m: dict) -> str:
    if heat >= 75 and m["volSurge"] > 0.5:
        return "on fire"
    if heat >= 60:
        return "hot"
    if m["ret5dPct"] < -8:
        return "falling knife"
    return "watch"


def _mark_prices(book: dict, prices: dict[str, float]) -> dict:
    cash = book.get("cash", 0.0)
    invested = 0.0
    for sym, pos in (book.get("positions") or {}).items():
        px = prices.get(sym, pos.get("avgPx", 0))
        qty = pos.get("qty", 0)
        mv = qty * px
        cost = pos.get("costBasis", qty * pos.get("avgPx", 0))
        pos["lastPx"] = round(px, 4)
        pos["marketValue"] = round(mv, 2)
        pos["unrealizedPnl"] = round(mv - cost, 2)
        invested += mv
    book["equity"] = round(cash + invested, 2)
    book["investedValue"] = round(invested, 2)
    return book


def tick() -> dict:
    """One desk pulse: scan, paper-trade top heat, mark, enforce stops."""
    cfg = load_config()
    book = load_book()
    ranked = scan_universe(cfg, limit=800)
    prices = {r["symbol"]: r["lastPx"] for r in ranked}

    # mark existing + stops
    closed = []
    for sym, pos in list((book.get("positions") or {}).items()):
        px = prices.get(sym)
        if px is None:
            continue
        avg = pos.get("avgPx", px)
        ret = (px / avg - 1.0) if avg else 0.0
        if ret <= -cfg["stopLossPct"] or ret >= cfg["takeProfitPct"]:
            qty = pos.get("qty", 0)
            cash_back = qty * px
            book["cash"] = book.get("cash", 0) + cash_back
            closed.append({
                "sym": sym, "reason": "stop" if ret < 0 else "target",
                "pnl": round(cash_back - pos.get("costBasis", 0), 2),
                "retPct": round(ret * 100, 2),
            })
            del book["positions"][sym]

    # open new top picks
    opened = []
    positions = book.get("positions") or {}
    max_pos = int(cfg["maxPositions"])
    top_n = int(cfg["topPicksPerTick"])
    equity = book.get("cash", 0) + sum(
        p.get("qty", 0) * prices.get(s, p.get("avgPx", 0))
        for s, p in positions.items()
    )
    slot = 0
    for row in ranked:
        if slot >= top_n or len(positions) >= max_pos:
            break
        sym = row["symbol"]
        if sym in positions:
            continue
        if row["heat"] < 55:
            continue
        px = row["lastPx"]
        stake = equity * float(cfg["maxPositionPct"])
        if stake > book.get("cash", 0) or stake < px:
            continue
        qty = stake / px
        book["cash"] = round(book.get("cash", 0) - stake, 2)
        positions[sym] = {
            "qty": round(qty, 4),
            "avgPx": px,
            "costBasis": round(stake, 2),
            "openedAt": _now(),
            "heat": row["heat"],
            "tag": row["tag"],
        }
        opened.append(sym)
        slot += 1

    book["positions"] = positions
    _mark_prices(book, prices)
    book["closedTrades"] = (book.get("closedTrades") or [])[-200:] + closed
    book["lastTick"] = _now()
    _save_json(BOOK_PATH, book)

    return {
        "ok": True,
        "scanned": len(ranked),
        "opened": opened,
        "closed": closed,
        "nPositions": len(positions),
        "equity": book.get("equity"),
        "top5": ranked[:5],
    }


def overview() -> dict:
    cfg = load_config()
    book = load_book()
    scan = _load_json(SCAN_PATH, {})
    ranked = scan.get("top") or []
    if not ranked:
        ranked = scan_universe(cfg, limit=30)[:30]
    prices = {r["symbol"]: r["lastPx"] for r in ranked}
    for sym in book.get("positions", {}):
        if sym not in prices and ranked:
            pass
    _mark_prices(book, {**prices, **{s: p.get("lastPx", p.get("avgPx")) for s, p in book.get("positions", {}).items()}})
    starting = book.get("startingCash", 100_000)
    equity = book.get("equity", starting)
    return {
        "name": "Penny Wolf",
        "tagline": "Sub-$5 momentum desk · paper only",
        "config": cfg,
        "book": {
            "equity": equity,
            "cash": book.get("cash"),
            "returnPct": round((equity / starting - 1) * 100, 3) if starting else 0,
            "nPositions": len(book.get("positions") or {}),
            "nClosed": len(book.get("closedTrades") or []),
        },
        "heatmap": ranked[:25],
        "lastScan": scan.get("generatedAt"),
        "ml": _penny_ml_status(),
        "disclaimer": "Research/paper simulation — not investment advice. Penny stocks are high risk.",
    }


def _penny_ml_status() -> dict:
    from pathlib import Path as P
    ml_dir = PENNY_DIR / "ml"
    status_path = ml_dir / "search_status.json"
    champ_path = ml_dir / "champion.json"
    out = {"search": _load_json(status_path, {}), "champion": None}
    if champ_path.exists():
        out["champion"] = _load_json(champ_path, None)
    onnx = REPO / "models" / "penny" / "champion.onnx"
    out["onnxReady"] = onnx.exists()
    try:
        from npu_runtime import write_status, primary_provider, qnn_devices
        write_status({"pennyWolfProbe": True})
        out["npuProviders"] = _load_json(REPO / "data" / "learning" / "npu_status.json", {}).get("available", [])
        out["npuPrimary"] = primary_provider()
        out["qnnDevices"] = len(qnn_devices())
    except Exception:
        out["npuProviders"] = []
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "tick":
        print(json.dumps(tick(), indent=2))
    else:
        print(json.dumps(overview(), indent=2))
