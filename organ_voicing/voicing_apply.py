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
    """How many Tabs to reach the next note's amplitude field."""
    return octave if next_note % 12 == 0 else normal  # next note is a C


def press_tabs(n: int, delay: float = 0.03) -> None:
    pag, _ = _backends()
    for _ in range(n):
        pag.press("tab")
        time.sleep(delay)


def apply_pass(
    notes: list[int],
    corrections: list[float],
    *,
    tab_normal: int = 4,
    tab_octave: int = 6,
    key_delay: float = 0.03,
    settle: float = 0.06,
    clamp=(-40.0, 40.0),
    should_stop=lambda: False,
    on_step=lambda i, note, old, new: None,
) -> list[tuple[int, float, float]]:
    """Walk the rank, adding each correction to the field's current value.

    Reads the current value (non-destructive — preserves existing voicing),
    adds the correction, writes it back, then Tabs to the next note. Returns a
    list of (note, old_value, new_value).
    """
    if len(notes) != len(corrections):
        raise ApplyError("notes and corrections length mismatch.")
    applied: list[tuple[int, float, float]] = []
    n = len(notes)
    for i, note in enumerate(notes):
        if should_stop():
            break
        old = read_value(settle)
        new = old + float(corrections[i])
        new = max(clamp[0], min(clamp[1], new))
        write_value(new, settle)
        applied.append((note, old, new))
        on_step(i, note, old, new)
        if i < n - 1:
            press_tabs(tabs_to_next(notes[i + 1], tab_normal, tab_octave), key_delay)
    return applied
