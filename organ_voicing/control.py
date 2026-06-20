"""Closed-loop control helpers for the auto-voicer (pure / numpy — testable).

The loop is plain feedback: each pass we measure, compute correction =
target - measured, apply it, and repeat. We do NOT assume a change moves the
measurement 1:1 — the response can be much less, and some pipes need to be
pushed to the +/-24 dB rail. These helpers decide convergence and when a
pinned-at-the-rail note should be declared "done" so it stops blocking
convergence.
"""

from __future__ import annotations

import numpy as np


def worst_active_correction(correction, done) -> float:
    """Largest |correction| among notes not yet marked done (0 if none left)."""
    correction = np.asarray(correction, dtype=np.float64)
    done = np.asarray(done, dtype=bool)
    active = ~done
    if not active.any():
        return 0.0
    return float(np.max(np.abs(correction[active])))


def update_done(notes, applied, correction, done, stuck, *,
                limit: float = 24.0, stuck_rounds: int = 3, eps: float = 1e-6):
    """Update the done/stuck state after an apply pass.

    `applied` maps note -> (old_value, new_value) for notes that were written.
    A note is "pinned" when it landed on a rail (new == +/-limit) yet the desired
    value wanted to go further past it. After `stuck_rounds` consecutive pinned
    rounds the note is marked done. Any non-pinned round resets its counter.

    Mutates `done` and `stuck` in place and returns the list of newly-done notes.
    """
    correction = np.asarray(correction, dtype=np.float64)
    newly_done = []
    for i, note in enumerate(notes):
        if note not in applied:
            continue
        old, new = applied[note]
        desired = old + float(correction[i])
        pinned = ((new >= limit - eps and desired > limit + eps) or
                  (new <= -limit + eps and desired < -limit - eps))
        if pinned:
            stuck[i] += 1
            if stuck[i] >= stuck_rounds and not done[i]:
                done[i] = True
                newly_done.append(note)
        else:
            stuck[i] = 0
    return newly_done
