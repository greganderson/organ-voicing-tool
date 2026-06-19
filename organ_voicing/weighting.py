"""Loudness weighting and level measurement.

We care about *perceived* loudness, not raw electrical level, so the meter
applies A-weighting (IEC 61672) before computing RMS. A-weighting is applied in
the frequency domain so we only depend on numpy.

All levels are reported in dBFS (0 dB = digital full scale). For voicing we only
ever compare notes *to each other*, so the absolute reference does not matter —
only that the same scale is used consistently.
"""

from __future__ import annotations

import numpy as np

# Floor used so a silent buffer reports a finite, very-low dB value
# instead of -inf (which breaks plotting/averaging).
_MIN_DB = -120.0
_EPS = 10.0 ** (_MIN_DB / 20.0)


def a_weight_gain(freqs: np.ndarray) -> np.ndarray:
    """Linear A-weighting gain for an array of frequencies (Hz).

    Implements the standard analog A-weighting transfer function magnitude,
    normalised to 0 dB at 1 kHz.
    """
    f = np.asarray(freqs, dtype=np.float64)
    f2 = f * f
    c1 = 20.598997 ** 2
    c2 = 107.65265 ** 2
    c3 = 737.86223 ** 2
    c4 = 12194.217 ** 2

    num = (c4 * f2 * f2)
    den = (f2 + c1) * np.sqrt((f2 + c2) * (f2 + c3)) * (f2 + c4)
    # Avoid divide-by-zero at DC.
    with np.errstate(divide="ignore", invalid="ignore"):
        ra = np.where(den > 0, num / den, 0.0)
    # +1.9997 dB normalisation so the curve is 0 dB at 1 kHz.
    gain = ra * (10.0 ** (1.9997 / 20.0))
    return gain


def a_weighted_rms(samples: np.ndarray, samplerate: int) -> float:
    """A-weighted RMS of a mono signal, returned in dBFS."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    n = x.size
    if n == 0:
        return _MIN_DB

    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n, d=1.0 / samplerate)
    weighted = spectrum * a_weight_gain(freqs)
    # Parseval: RMS of the weighted time signal without a round-trip IFFT.
    # sum(|X_k|^2) over the full spectrum / n^2 == mean(x^2).
    power = (np.abs(weighted[0]) ** 2)
    if n % 2 == 0:
        power += np.abs(weighted[-1]) ** 2
        power += 2.0 * np.sum(np.abs(weighted[1:-1]) ** 2)
    else:
        power += 2.0 * np.sum(np.abs(weighted[1:]) ** 2)
    mean_sq = power / (n * n)

    rms = np.sqrt(max(mean_sq, _EPS * _EPS))
    return float(20.0 * np.log10(max(rms, _EPS)))


def unweighted_rms(samples: np.ndarray) -> float:
    """Plain (Z-weighted) RMS in dBFS — used for the noise-floor check."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    if x.size == 0:
        return _MIN_DB
    rms = np.sqrt(np.mean(x * x))
    return float(20.0 * np.log10(max(rms, _EPS)))


def peak_dbfs(samples: np.ndarray) -> float:
    """Peak sample level in dBFS — used for clip warnings."""
    x = np.asarray(samples, dtype=np.float64).ravel()
    if x.size == 0:
        return _MIN_DB
    peak = float(np.max(np.abs(x)))
    return float(20.0 * np.log10(max(peak, _EPS)))


MIN_DB = _MIN_DB
