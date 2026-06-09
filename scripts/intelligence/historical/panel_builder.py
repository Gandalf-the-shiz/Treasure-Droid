"""Build a historical panel matching live Treasure Droid outputs.

Merges predictor val+test exports with point-in-time price sleeves and the
same neutralized alpha frame the live engine produces. This is the dataset the
Mad Scientist Lab walks forward day-by-day.

Output: data/intelligence/historical/panel.parquet + panel_meta.json

Usage:
  python scripts/intelligence/historical/panel_builder.py
  python scripts/intelligence/historical/panel_builder.py --start 2024-01-01 --end 2025-12-31
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PRED_DIR = REPO / "data" / "predictions_v3"
OUT_DIR = REPO / "data" / "intelligence" / "historical"
PANEL_PARQUET = OUT_DIR / "panel.parquet"
PANEL_CSV = OUT_DIR / "panel.csv.gz"
META_PATH = OUT_DIR / "panel_meta.json"
CONFIG_PATH = REPO / "config" / "mad_scientist_lab.json"

sys.path.insert(0, str(REPO / "scripts"))
from intelligence.alpha.measure import _price_sleeves, _size_map  # noqa: E402
from intelligence.alpha.engine import enrich_panel_alpha  # noqa: E402

_RET_COLS = ["y_ret", "fwd_ret", "forward_ret", "realized_ret", "target_ret", "ret_fwd_1"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_config() -> dict:
    defaults = {
        "train_end": "2023-12-31",
        "walkforward_start": "2024-01-01",
        "walkforward_end": "2025-12-31",
        "panel_sources": ["val.csv", "test.csv"],
        "max_symbols_per_day": 0,
    }
    if CONFIG_PATH.exists():
        try:
            defaults.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            pass
    return defaults


def _load_predictor_exports(sources: list[str]) -> pd.DataFrame:
    frames = []
    for name in sources:
        p = PRED_DIR / name
        if not p.exists():
            print(f"[panel] skip missing {name}", flush=True)
            continue
        df = pd.read_csv(p)
        df.columns = [c.strip().lower() for c in df.columns]
        frames.append(df)
        print(f"[panel] loaded {name}: {len(df):,} rows", flush=True)
    if not frames:
        raise SystemExit("no val.csv or test.csv — run train-predictor-v3.py first")
    return pd.concat(frames, ignore_index=True)


def _load_close_prices() -> dict[str, dict[str, float]]:
    """symbol -> date_str -> close (for panel price column)."""
    hist = REPO / "data" / "historical"
    out: dict[str, dict[str, float]] = {}
    if not hist.exists():
        return out
    for fp in hist.glob("*.json"):
        if fp.name.startswith("manifest") or "coverage" in fp.name:
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for sym, payload in (data.get("stocks") or {}).items():
            candles = (payload or {}).get("candles") or []
            if not candles:
                continue
            sym_u = str(sym).upper()
            dmap = out.setdefault(sym_u, {})
            for c in candles:
                d = str(c.get("date", ""))[:10]
                cl = c.get("close")
                if d and cl is not None:
                    try:
                        dmap[d] = float(cl)
                    except (TypeError, ValueError):
                        pass
    return out


def build_panel(
    *,
    start: str | None = None,
    end: str | None = None,
    max_per_day: int = 0,
) -> dict:
    cfg = _load_config()
    start = start or cfg["walkforward_start"]
    end = end or cfg["walkforward_end"]
    max_per_day = max_per_day or int(cfg.get("max_symbols_per_day") or 0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = _load_predictor_exports(cfg.get("panel_sources") or ["val.csv", "test.csv"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["date", "symbol", "pred_proba_up", "pred_ret"])
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()

    ret_col = next((c for c in _RET_COLS if c in df.columns), None)
    if ret_col is None:
        raise SystemExit(f"panel missing return column (need one of {_RET_COLS})")
    if "sector" not in df.columns:
        df["sector"] = "UNKNOWN"

    try:
        from intelligence.tradeable_universe import is_tradeable
        df = df.loc[df["symbol"].map(lambda s: is_tradeable(s)[0])].copy()
    except Exception:
        pass

    print(f"[panel] walkforward window {start}..{end} tradeable rows={len(df):,}", flush=True)

    ps = _price_sleeves()
    if not ps.empty:
        df = df.merge(ps, on=["symbol", "date"], how="left")
        df = df.rename(columns={
            "rev_1": "reversal_1d",
            "rev_5": "reversal_5d",
            "mom_120_20": "momentum_120_20",
        })
        print(f"[panel] merged PIT price sleeves", flush=True)

    closes = _load_close_prices()
    if closes:
        df["price"] = [
            closes.get(str(r["symbol"]).upper(), {}).get(str(r["date"]), 0.0)
            for _, r in df.iterrows()
        ]
    else:
        df["price"] = 0.0

    size_map = _size_map()
    df["_size"] = df["symbol"].map(size_map).astype(float)

    if max_per_day > 0:
        df["edge"] = (2.0 * df["pred_proba_up"].astype(float) - 1.0) * df["pred_ret"].astype(float).abs()
        df = (
            df.sort_values(["date", "edge"], ascending=[True, False])
            .groupby("date", group_keys=False)
            .head(max_per_day)
        )

    print(f"[panel] enriching alpha frame ({df['date'].nunique()} dates)…", flush=True)
    df = enrich_panel_alpha(df, size_col="_size")
    df["y_ret"] = df[ret_col].astype(float) if ret_col != "y_ret" else df["y_ret"].astype(float)

    panel_cols = [
        "date", "symbol", "sector", "price", "pred_proba_up", "pred_ret", "edge", "alpha", "y_ret",
        "reversal_1d", "reversal_5d", "momentum_120_20",
    ] + [c for c in df.columns if c.startswith("n_")]
    panel_cols = [c for c in panel_cols if c in df.columns]
    panel = df[panel_cols].copy()

    out_path = PANEL_PARQUET
    try:
        panel.to_parquet(PANEL_PARQUET, index=False)
    except (ImportError, ValueError, OSError):
        out_path = PANEL_CSV
        panel.to_csv(PANEL_CSV, index=False, compression="gzip")
        print(f"[panel] pyarrow missing — wrote {PANEL_CSV.name}", flush=True)
    meta = {
        "generatedAt": _now(),
        "ok": True,
        "mantra": "mad_scientist",
        "train_end": cfg["train_end"],
        "walkforward": {"start": start, "end": end},
        "n_rows": int(len(panel)),
        "n_days": int(panel["date"].nunique()),
        "n_symbols": int(panel["symbol"].nunique()),
        "columns": panel_cols,
        "path": str(out_path.relative_to(REPO)),
        "matches_live": [
            "date", "symbol", "sector", "pred_proba_up", "pred_ret",
            "edge", "alpha", "price", "n_<sleeve>",
        ],
        "note": (
            "Panel built from predictor exports (8yr-trained model) + PIT price sleeves + "
            "same neutralization as live alpha engine. Sparse sleeves (PEAD/revisions/sentiment) "
            "omitted in history until dated feeds are backfilled."
        ),
    }
    META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"[panel] wrote {out_path.name} rows={meta['n_rows']:,} "
        f"days={meta['n_days']} symbols={meta['n_symbols']}",
        flush=True,
    )
    return meta


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Mad Scientist historical panel builder")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--max-per-day", type=int, default=0)
    args = ap.parse_args()
    build_panel(start=args.start, end=args.end, max_per_day=args.max_per_day)
