"""MIDI note number <-> name helpers (no third-party dependencies)."""

from __future__ import annotations

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(note: int) -> str:
    """MIDI note number -> name like 'C4' (C4 = 60)."""
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def parse_note(text: str) -> int:
    """Accept either a MIDI number ('60') or a name ('C4', 'f#3')."""
    text = text.strip()
    if not text:
        raise ValueError("empty note")
    if text.lstrip("-").isdigit():
        n = int(text)
        if not 0 <= n <= 127:
            raise ValueError("MIDI note out of range 0-127")
        return n
    s = text[0].upper() + text[1:].replace("♯", "#")
    i = 2 if (len(s) > 1 and s[1] == "#") else 1
    name = s[:i]
    octave = s[i:]
    if name not in NOTE_NAMES or not octave.lstrip("-").isdigit():
        raise ValueError(f"can't parse note '{text}'")
    return NOTE_NAMES.index(name) + (int(octave) + 1) * 12
