"""Walk-forward folds for penny ML."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Fold:
    train_dates: np.ndarray
    test_dates: np.ndarray
    fold_index: int


def walk_forward_folds(dates, n_splits: int = 5, label_horizon: int = 5) -> list[Fold]:
    uniq = pd.DatetimeIndex(pd.to_datetime(pd.unique(pd.Series(dates)))).sort_values()
    n = len(uniq)
    if n < n_splits + 2:
        return []
    block = n // (n_splits + 1)
    folds = []
    for i in range(n_splits):
        test_start = block * (i + 1)
        test_end = block * (i + 2) if i < n_splits - 1 else n
        test_dates = uniq[test_start:test_end]
        purge_cut = max(0, test_start - label_horizon)
        train_dates = uniq[:purge_cut]
        if len(train_dates) and len(test_dates):
            folds.append(Fold(train_dates.to_numpy(), test_dates.to_numpy(), i))
    return folds
