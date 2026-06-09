"""Cross-sectional alpha factory (Alpha Doctrine, Phase A).

Turns absolute single-signal predictions into a neutralized, market-neutral,
breadth-scaled book. See docs/ALPHA_DOCTRINE.md.
"""
from .neutralize import (
    cs_rank,
    cs_zscore,
    demean_by_group,
    neutralize_series,
    winsorize,
)

__all__ = [
    "cs_rank",
    "cs_zscore",
    "demean_by_group",
    "neutralize_series",
    "winsorize",
]
