"""Unattended rank scan: MIDI-walk a note range and measure each note.

Plays each note in turn (with a gap afterward so the room/reverb tail decays
before the next note), measures the steady-state loudness, optionally averages
repeats, and reports progress via a callback so the GUI can update live and the
user can stop early.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .audio import AudioMeter
from .midi_out import MidiPlayer
from .notes import note_name


@dataclass
class NoteResult:
    note: int
    name: str
    a_weighted_db: float
    peak_db: float
    snr_db: float | None    # above noise floor, if known
    clipped: bool
    low_snr: bool


def _avg_db(db_values: list[float]) -> float:
    """Average several dB readings by their linear power (correct for RMS)."""
    arr = np.asarray(db_values, dtype=np.float64)
    power = 10.0 ** (arr / 10.0)        # dB here is 20*log10(rms) -> power = rms^2
    return float(10.0 * np.log10(np.mean(power)))


def scan_rank(
    meter: AudioMeter,
    player: MidiPlayer,
    low_note: int,
    high_note: int,
    *,
    channel: int = 0,
    velocity: int = 100,
    duration_s: float = 1.5,
    gap_s: float = 0.6,
    repeats: int = 1,
    skip_attack_s: float = 0.3,
    noise_floor_db: float | None = None,
    low_snr_margin_db: float = 12.0,
    should_stop=lambda: False,
    on_progress=lambda done, total, result: None,
) -> list[NoteResult]:
    """Scan low_note..high_note inclusive. Returns a NoteResult per note."""
    if not meter.running:
        raise RuntimeError("Audio stream is not running.")
    if not player.is_open:
        raise RuntimeError("No MIDI output port is open.")

    notes = list(range(low_note, high_note + 1))
    total = len(notes)
    results: list[NoteResult] = []

    for idx, note in enumerate(notes):
        if should_stop():
            break

        readings: list[float] = []
        peak = -999.0
        for _ in range(max(1, repeats)):
            if should_stop():
                break
            # Hold the note slightly longer than the capture so it sustains
            # through the whole measurement window.
            player.play_note(note, velocity=velocity, channel=channel,
                             duration_s=duration_s + 0.4, blocking=False)
            time.sleep(0.05)
            m = meter.capture(duration_s=duration_s, skip_attack_s=skip_attack_s)
            readings.append(m.a_weighted_db)
            peak = max(peak, m.peak_db)
            time.sleep(gap_s)  # let the reverb tail decay before the next read

        if not readings:
            break

        db = _avg_db(readings)
        snr = (db - noise_floor_db) if noise_floor_db is not None else None
        res = NoteResult(
            note=note,
            name=note_name(note),
            a_weighted_db=db,
            peak_db=peak,
            snr_db=snr,
            clipped=peak > -0.5,
            low_snr=(snr is not None and snr < low_snr_margin_db),
        )
        results.append(res)
        on_progress(idx + 1, total, res)

    # Safety: make sure nothing is left ringing.
    try:
        player.all_notes_off(channel)
    except Exception:
        pass
    return results
