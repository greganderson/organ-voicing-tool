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


def test_flat_target_is_median():
    from organ_voicing import analysis
    vals = [-40, -38, -36, -34, -50]  # median -38
    tgt = analysis.make_target(vals, mode="flat")
    assert np.allclose(tgt, -38.0)


def test_tab_count_rule():
    from organ_voicing import voicing_apply as va
    from organ_voicing.notes import parse_note
    # 6 tabs only when the NEXT note is a C (B->C octave boundary), else 4.
    assert va.tabs_to_next(parse_note("C4")) == 6   # next note is C4
    assert va.tabs_to_next(parse_note("C5")) == 6
    assert va.tabs_to_next(parse_note("D4")) == 4
    assert va.tabs_to_next(parse_note("B3")) == 4
    assert va.tabs_to_next(parse_note("F#3")) == 4


def test_autovoice_converges_in_simulation():
    """The closed loop should flatten a rank in 1-2 passes.

    Models reality: each note's measured level = its amplitude trim + a fixed
    per-note room/sample constant K. Applying correction (= target - measured)
    to the trim moves the measurement 1:1, so it should converge fast.
    """
    from organ_voicing import analysis
    rng = np.random.default_rng(0)
    K = rng.normal(0, 3.0, size=30)        # per-note room+sample offsets
    trim = np.zeros(30)                     # current voicing trims (start at 0)
    for _ in range(3):
        measured = trim + K
        target = analysis.make_target(measured, mode="flat")
        corr = target - measured
        trim = trim + corr                  # "apply"
    measured = trim + K
    assert measured.max() - measured.min() < 0.5   # essentially flat


class _FakeRig:
    """Models Hauptwerk's voicing fields: amplitude fields spaced 4 apart, 6 at
    a B->C boundary, with dummy fields in between. Doubles as fake pyautogui +
    pyperclip so we can drive voicing_apply.apply_pass with no real keyboard."""

    FAILSAFE = True

    def __init__(self, notes, init_values):
        pos = 0
        self.note_to_pos = {notes[0]: 0}
        for k in range(1, len(notes)):
            pos += 6 if notes[k] % 12 == 0 else 4
            self.note_to_pos[notes[k]] = pos
        self.pos_to_note = {p: n for n, p in self.note_to_pos.items()}
        self.values = dict(init_values)
        self.focus = self.note_to_pos[notes[0]]
        self.clipboard = ""

    # pyperclip side
    def copy(self, s): self.clipboard = s
    def paste(self): return self.clipboard

    # pyautogui side
    def press(self, key):
        if key == "tab":
            self.focus += 1

    def hotkey(self, *keys):
        if keys == ("shift", "tab"):
            self.focus -= 1
        elif keys == ("ctrl", "c"):
            note = self.pos_to_note.get(self.focus)
            if note is not None:
                self.clipboard = f"{self.values[note]:.1f}"
        elif keys == ("ctrl", "v"):
            note = self.pos_to_note.get(self.focus)
            if note is not None:
                self.values[note] = float(self.clipboard)


def test_apply_pass_navigation_both_directions():
    from organ_voicing import voicing_apply as va
    notes = list(range(57, 64))           # A3..D#4, crossing the B3->C4 boundary
    rig = _FakeRig(notes, {n: 0.0 for n in notes})
    va._backends = lambda: (rig, rig)     # inject fake keyboard/clipboard

    # Forward: distinct corrections must land on the right notes.
    corr = [float(i + 1) for i in range(len(notes))]
    va.apply_pass(notes, corr, reverse=False, key_delay=0, settle=0)
    for i, n in enumerate(notes):
        assert abs(rig.values[n] - corr[i]) < 1e-9, (n, rig.values[n])
    assert rig.focus == rig.note_to_pos[notes[-1]]   # ended on the top note

    # Reverse continues from the top note (no reposition) and adds correctly.
    va.apply_pass(notes, [10.0] * len(notes), reverse=True, key_delay=0, settle=0)
    for i, n in enumerate(notes):
        assert abs(rig.values[n] - (corr[i] + 10.0)) < 1e-9, (n, rig.values[n])
    assert rig.focus == rig.note_to_pos[notes[0]]    # ended back on the bottom note


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
