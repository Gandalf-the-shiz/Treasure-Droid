"""Point-in-time features for penny-stock panel rows."""
from __future__ import annotations

import numpy as np
import pandas as pd


FEATURE_NAMES = [
    "ret_1", "ret_5", "ret_10", "ret_20", "ret_60",
    "mom_20", "mom_60", "vol_10", "vol_20", "vol_60",
    "max_ret_20", "min_ret_20", "amihud_20", "log_dollar_vol",
    "rsi_14", "sma20_ratio", "drawdown_60", "dist_252_high",
    "turnover_z", "hl_range",
]


def features_from_candles(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype("float64")
    h = df["high"].astype("float64")
    low = df["low"].astype("float64")
    v = df["volume"].astype("float64")
    out = pd.DataFrame(index=df.index)
    r1 = c.pct_change()
    out["ret_1"] = r1
    out["ret_5"] = c.pct_change(5)
    out["ret_10"] = c.pct_change(10)
    out["ret_20"] = c.pct_change(20)
    out["ret_60"] = c.pct_change(60)
    out["mom_20"] = c / c.shift(20) - 1.0
    out["mom_60"] = c / c.shift(60) - 1.0
    out["vol_10"] = r1.rolling(10).std()
    out["vol_20"] = r1.rolling(20).std()
    out["vol_60"] = r1.rolling(60).std()
    out["max_ret_20"] = r1.rolling(20).max()
    out["min_ret_20"] = r1.rolling(20).min()
    dollar = (c * v).replace(0, np.nan)
    out["amihud_20"] = (r1.abs() / dollar).rolling(20).mean() * 1e9
    out["log_dollar_vol"] = np.log(dollar.rolling(20).mean())
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["rsi_14"] = (100 - 100 / (1 + rs)) / 100.0
    out["sma20_ratio"] = c / c.rolling(20).mean() - 1.0
    out["drawdown_60"] = c / c.rolling(60, min_periods=20).max() - 1.0
    out["dist_252_high"] = c / c.rolling(252, min_periods=60).max() - 1.0
    out["turnover_z"] = (v - v.rolling(60).mean()) / v.rolling(60).std()
    out["hl_range"] = (h - low) / c
    return out.replace([np.inf, -np.inf], np.nan)
