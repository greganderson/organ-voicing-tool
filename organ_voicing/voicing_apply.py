"""Keyboard + clipboard automation of Hauptwerk's Pipe & rank voicing screen.

This drives the amplitude (dB) fields directly — no mouse/pixel hunting — relying
on the confirmed behaviour of that screen:

  * Tabbing into an amplitude field auto-selects its current value.
  * Ctrl+C copies the value; Ctrl+V replaces it; the value commits instantly
    (no Enter needed).
  * Advancing to the next note's amplitude field = 4 Tabs, or 6 when the next
    note is a C (the B->C octave boundary).

Usage model: the user clicks the FIRST scanned note's amplitude field to give it
focus, then we send keystrokes to whatever window is focused. The caller must
keep Hauptwerk focused and hands off the keyboard/mouse during a pass.

pyautogui / pyperclip are imported lazily so the rest of the app (measurement)
runs even where they aren't installed.
"""

from __future__ import annotations

import time


class ApplyError(RuntimeError):
    pass


def _backends():
    try:
        import pyautogui
        import pyperclip
    except Exception as e:  # pragma: no cover - depends on OS/install
        raise ApplyError(
            "Auto-apply needs the 'pyautogui' and 'pyperclip' packages "
            "(pip install pyautogui pyperclip)."
        ) from e
    # Mouse to a screen corner aborts pyautogui — keep that safety on.
    pyautogui.FAILSAFE = True
    return pyautogui, pyperclip


def read_value(settle: float = 0.06) -> float:
    """Copy the focused field and parse it as a float.

    Raises ApplyError if the clipboard doesn't come back as a number — which is
    the symptom of the wrong field (or no field) being focused, so we stop
    rather than write garbage.
    """
    pag, clip = _backends()
    sentinel = "\x00__hw__"
    clip.copy(sentinel)              # so a no-op copy is detectable
    pag.hotkey("ctrl", "c")
    time.sleep(settle)
    txt = clip.paste().strip()
    if txt == sentinel or txt == "":
        raise ApplyError("Couldn't read the amplitude value — is the first "
                         "note's field focused in Hauptwerk?")
    try:
        return float(txt.replace(",", "."))
    except ValueError as e:
        raise ApplyError(f"Focused field wasn't a number (got {txt!r}).") from e


def write_value(value: float, settle: float = 0.06) -> None:
    """Set the focused (auto-selected) field to `value` via clipboard paste."""
    pag, clip = _backends()
    clip.copy(f"{value:.1f}")
    pag.hotkey("ctrl", "v")
    time.sleep(settle)


def tabs_to_next(next_note: int, normal: int = 4, octave: int = 6) -> int:
    """How many Tabs between a note and its neighbour.

    The B<->C boundary costs `octave` (6); every other step costs `normal` (4).
    The gap is symmetric, so this is correct in both directions as long as you
    pass the *upper* of the two notes (the C at a boundary).
    """
    return octave if next_note % 12 == 0 else normal


def press_tabs(n: int, delay: float = 0.03, reverse: bool = False) -> None:
    pag, _ = _backends()
    for _ in range(n):
        if reverse:
            pag.hotkey("shift", "tab")
        else:
            pag.press("tab")
        time.sleep(delay)


def apply_pass(
    notes: list[int],
    corrections: list[float],
    *,
    reverse: bool = False,
    tab_normal: int = 4,
    tab_octave: int = 6,
    key_delay: float = 0.03,
    settle: float = 0.06,
    clamp=(-24.0, 24.0),
    should_stop=lambda: False,
    on_step=lambda i, note, old, new: None,
) -> list[tuple[int, float, float]]:
    """Walk the rank, adding each correction to the field's current value.

    Reads the current value (non-destructive — preserves existing voicing),
    adds the correction, writes it back, then moves to the neighbouring note.

    `corrections[i]` always applies to `notes[i]`, regardless of direction.
    Forward (low→high) ends focus on the top note; reverse (high→low) ends on
    the bottom note — so alternating passes never need to reposition focus.
    Returns a list of (note, old_value, new_value) in the order visited.
    """
    if len(notes) != len(corrections):
        raise ApplyError("notes and corrections length mismatch.")
    n = len(notes)
    order = range(n - 1, -1, -1) if reverse else range(n)

    applied: list[tuple[int, float, float]] = []
    prev_i: int | None = None
    for i in order:
        if should_stop():
            break
        if prev_i is not None:
            # The expensive (6-Tab) step is the one touching a C. Forward we're
            # entering notes[i]; reverse we're leaving notes[prev_i] (the upper).
            boundary_note = notes[i] if not reverse else notes[prev_i]
            steps = tabs_to_next(boundary_note, tab_normal, tab_octave)
            press_tabs(steps, key_delay, reverse=reverse)
        old = read_value(settle)
        new = max(clamp[0], min(clamp[1], old + float(corrections[i])))
        write_value(new, settle)
        applied.append((notes[i], old, new))
        on_step(i, notes[i], old, new)
        prev_i = i
    return applied
