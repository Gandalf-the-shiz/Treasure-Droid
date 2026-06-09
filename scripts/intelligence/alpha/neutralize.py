"""Cross-sectional neutralization primitives (Alpha Doctrine pillar 5).

Every alpha sleeve is winsorized, demeaned against sector & size buckets, then
rank/z-scored before combination. This is what converts a microcap-trapped raw
IC into a tradeable, market-neutral signal (fixes negative quintile spread).

Pure functions only — no I/O, fully unit-testable.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def winsorize(s: pd.Series, limit: float = 0.02) -> pd.Series:
    """Clip a series to its [limit, 1-limit] quantiles to tame outliers."""
    if s is None or s.empty:
        return s
    valid = s.dropna()
    if valid.empty:
        return s
    lo = valid.quantile(limit)
    hi = valid.quantile(1.0 - limit)
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return s
    return s.clip(lower=lo, upper=hi)


def cs_rank(s: pd.Series, centered: bool = True) -> pd.Series:
    """Cross-sectional rank in [0,1] (or [-0.5,0.5] if centered)."""
    if s is None or s.empty:
        return s
    r = s.rank(method="average", pct=True)
    return r - 0.5 if centered else r


def cs_zscore(s: pd.Series) -> pd.Series:
    """Cross-sectional z-score; returns zeros if degenerate."""
    if s is None or s.empty:
        return s
    mu = s.mean()
    sd = s.std(ddof=0)
    if not np.isfinite(sd) or sd == 0:
        return pd.Series(0.0, index=s.index)
    return (s - mu) / sd


def demean_by_group(s: pd.Series, groups: pd.Series | None) -> pd.Series:
    """Subtract the per-group mean (sector/size neutralization)."""
    if s is None or s.empty or groups is None:
        return s
    groups = groups.reindex(s.index)
    if groups.isna().all():
        return s - s.mean()
    return s - s.groupby(groups).transform("mean")


def size_buckets(size: pd.Series | None, n: int = 5) -> pd.Series | None:
    """Quantile-bucket a size proxy (e.g. log dollar volume) into n groups."""
    if size is None or size.dropna().empty:
        return None
    try:
        return pd.qcut(size.rank(method="first"), q=n, labels=False, duplicates="drop")
    except (ValueError, IndexError):
        return None


def neutralize_series(
    raw: pd.Series,
    *,
    sector: pd.Series | None = None,
    size: pd.Series | None = None,
    winsor: float = 0.02,
    output: str = "zscore",
) -> pd.Series:
    """Full neutralization pipeline for one sleeve on one cross-section.

    winsorize -> sector-demean -> size-bucket-demean -> rank/zscore.
    Returns a mean-zero, unit-scale signal comparable across sleeves.
    """
    if raw is None or raw.dropna().empty:
        return raw
    s = winsorize(raw.astype(float), winsor)
    s = demean_by_group(s, sector)
    s = demean_by_group(s, size_buckets(size))
    if output == "rank":
        return cs_rank(s, centered=True)
    return cs_zscore(s)


def spearman_ic(pred: pd.Series, fwd_ret: pd.Series) -> float:
    """Cross-sectional rank IC (Spearman) between a signal and forward returns."""
    df = pd.DataFrame({"p": pred, "r": fwd_ret}).dropna()
    if len(df) < 5:
        return float("nan")
    pr = df["p"].rank()
    rr = df["r"].rank()
    if pr.std(ddof=0) == 0 or rr.std(ddof=0) == 0:
        return float("nan")
    return float(np.corrcoef(pr, rr)[0, 1])


def quantile_spread(pred: pd.Series, fwd_ret: pd.Series, q: int = 5) -> float:
    """Top-minus-bottom quantile mean forward return (the tradeable edge)."""
    df = pd.DataFrame({"p": pred, "r": fwd_ret}).dropna()
    if len(df) < q * 2:
        return float("nan")
    try:
        df["bucket"] = pd.qcut(df["p"].rank(method="first"), q=q, labels=False, duplicates="drop")
    except (ValueError, IndexError):
        return float("nan")
    top = df.loc[df["bucket"] == df["bucket"].max(), "r"].mean()
    bot = df.loc[df["bucket"] == df["bucket"].min(), "r"].mean()
    return float(top - bot)
