"""Sanity checks for the loudness math and note parsing (numpy only)."""

import numpy as np

from organ_voicing import weighting
from organ_voicing.notes import note_name, parse_note


def tone(freq, fs=48000, dur=1.0, amp=1.0):
    t = np.arange(int(fs * dur)) / fs
    return amp * np.sin(2 * np.pi * freq * t)


def test_a_weight_reference_points():
    # A-weighting is 0 dB at 1 kHz by definition.
    g = weighting.a_weight_gain(np.array([1000.0]))[0]
    assert abs(20 * np.log10(g)) < 0.05
    # Known textbook values (~±0.3 dB).
    def db(f):
        return 20 * np.log10(weighting.a_weight_gain(np.array([f]))[0])
    assert abs(db(100) - (-19.1)) < 0.4
    assert abs(db(10000) - (-2.5)) < 0.4


def test_full_scale_sine_level():
    # RMS of a unit-amplitude sine is 0.707 -> -3.01 dBFS; A-weight at 1k = 0 dB.
    x = tone(1000, amp=1.0)
    db = weighting.a_weighted_rms(x, 48000)
    assert abs(db - (-3.01)) < 0.1


def test_low_freq_is_attenuated():
    # A 100 Hz tone should read ~19 dB lower than a 1 kHz tone of equal amplitude.
    hi = weighting.a_weighted_rms(tone(1000), 48000)
    lo = weighting.a_weighted_rms(tone(100), 48000)
    assert (hi - lo) > 17.0


def test_amplitude_halving_is_minus_6db():
    a = weighting.a_weighted_rms(tone(1000, amp=1.0), 48000)
    b = weighting.a_weighted_rms(tone(1000, amp=0.5), 48000)
    assert abs((a - b) - 6.02) < 0.1


def test_silence_is_floor():
    assert weighting.a_weighted_rms(np.zeros(48000), 48000) <= weighting.MIN_DB + 0.01


def test_note_names_and_parse():
    assert note_name(60) == "C4"
    assert note_name(69) == "A4"
    assert parse_note("C4") == 60
    assert parse_note("60") == 60
    assert parse_note("f#3") == 54
    assert parse_note("A4") == 69
    assert parse_note("C2") == 36   # typical manual low note
    assert parse_note("C7") == 96   # typical manual high note


def test_analysis_flags_single_hot_pipe():
    from organ_voicing import analysis
    # A smooth rank with one note 4 dB hot in the middle.
    vals = list(np.linspace(-40, -38, 25))  # gentle regulation curve
    hot = 12
    vals[hot] += 4.0
    res = analysis.analyze(vals, window=7, tolerance_db=1.5)
    # The hot note is flagged, its neighbours are not.
    assert res.is_outlier[hot]
    assert not res.is_outlier[hot - 3]
    assert not res.is_outlier[hot + 3]
    # Correction pushes the hot note back down (negative).
    assert res.correction[hot] < -2.0


def test_curve_is_outlier_resistant():
    from organ_voicing import analysis
    # The fitted target near a hot pipe should NOT be dragged up to meet it
    # (median-based smoothing ignores the single spike).
    vals = [-40.0] * 25
    vals[12] += 6.0
    res = analysis.analyze(vals, window=7, tolerance_db=1.5)
    assert abs(res.target[12] - (-40.0)) < 0.6


def test_flat_rank_has_no_outliers():
    from organ_voicing import analysis
    rng = list(np.linspace(-40, -39, 30))
    res = analysis.analyze(rng, window=7, tolerance_db=1.5)
    assert res.is_outlier.sum() == 0


if __name__ == "__main__":
    import sys
    import traceback
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failed += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failed else 0)
