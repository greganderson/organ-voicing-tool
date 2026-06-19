"""Rank balance analysis.

A well-voiced rank is NOT flat — it follows a gentle regulation curve across the
keyboard. So we don't compare each note to a global average; we fit a smooth,
*outlier-resistant* trend through the rank and flag notes that deviate from
their neighbours. The suggested correction for each note is simply

    correction_dB = target_curve - measured

i.e. how much to turn that pipe up (+) or down (-) to sit on the curve.

The smoothing uses a median filter (so one hot pipe can't drag the curve toward
itself) followed by a light moving average. numpy only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _moving_median(values: np.ndarray, window: int) -> np.ndarray:
    n = values.size
    half = window // 2
    out = np.empty(n)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = np.median(values[lo:hi])
    return out


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    n = values.size
    half = window // 2
    out = np.empty(n)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        out[i] = np.mean(values[lo:hi])
    return out


def smooth_target(values, window: int = 7) -> np.ndarray:
    """Outlier-resistant target curve through the measured levels (dB)."""
    v = np.asarray(values, dtype=np.float64)
    if v.size == 0:
        return v
    window = max(3, window | 1)  # force odd, >= 3
    med = _moving_median(v, window)
    return _moving_average(med, 3)


@dataclass
class BalanceResult:
    target: np.ndarray        # fitted target level per note (dB)
    correction: np.ndarray    # target - measured (dB); + = turn up, - = turn down
    is_outlier: np.ndarray    # bool mask
    spread_db: float          # max-min of measured
    residual_std_db: float    # std of (measured - target)


def analyze(values, window: int = 7, tolerance_db: float = 1.5) -> BalanceResult:
    """Fit the curve and flag notes whose correction exceeds tolerance."""
    v = np.asarray(values, dtype=np.float64)
    target = smooth_target(v, window=window)
    correction = target - v
    is_outlier = np.abs(correction) >= tolerance_db
    spread = float(v.max() - v.min()) if v.size else 0.0
    resid_std = float(np.std(correction)) if v.size else 0.0
    return BalanceResult(
        target=target,
        correction=correction,
        is_outlier=is_outlier,
        spread_db=spread,
        residual_std_db=resid_std,
    )
