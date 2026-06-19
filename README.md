# Organ Voicing Tool

Measure and balance per-note loudness for a Hauptwerk sampleset, using a
measurement mic at your listening position so the result reflects *your room*.

This repo is currently at **Level 1 — the live meter**. It exists to confirm the
measurement chain works (mic → PC → loudness number) before building the
unattended rank scanner (Level 2) and the auto-voicer (Level 3).

## What Level 1 does

- Shows a **live A-weighted loudness meter** from your mic input.
- Measures the **noise floor** at the listening position.
- Measures a **single note's steady-state loudness** as a repeatable dBFS number
  (it skips the attack transient so the reading is stable).
- Optionally **fires the note into Hauptwerk over MIDI** so measuring is
  hands-free.
- Logs measurements to a table and **exports CSV**.

The numbers are *relative* (dBFS, 0 = digital full scale). For voicing we only
compare notes to each other, so absolute calibration isn't needed.

## Setup (Windows)

1. Install Python 3.11+ from python.org (tick "Add to PATH").
2. In a terminal in this folder:
   ```
   py -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Plug in your measurement mic. The Onkyo AccuEQ setup mic should work in the
   PC's pink mic jack (it supplies the bias electret mics need). If the level is
   weak, route it through a USB audio interface with a mic input.

## Run

```
python main.py
```

Then:
1. Pick your mic under **Microphone input** and click **Start**. Tap the mic —
   the meter should jump. (This is the key thing to confirm.)
2. Click **Measure noise floor** while the room is quiet.
3. To measure by hand: play a note in Hauptwerk and click **Measure (I'll play
   it)**.
4. To measure hands-free: pick your MIDI port (the one Hauptwerk listens on),
   click **Open**, set the note / channel / velocity, and click
   **▶ Play note + measure**. Solo a single stop in Hauptwerk first.
5. Use **Export CSV…** to save readings.

> Channel is 1–16 in the UI (matches Hauptwerk); make sure it matches the MIDI
> channel of the manual whose stop you've soloed.

## Things to check during this stage

- Does the mic register a clean signal with a sensible noise floor (ideally the
  floor sits well below where notes land — a 20 dB+ gap is comfortable)?
- Does repeating the same note give a repeatable number (within ~0.5 dB)?
- Does a loud note ever trip the **CLIP!** warning? If so, lower the mic input
  gain in Windows sound settings.

What we learn here sets the measurement parameters for the Level 2 scanner.

## Tests

Math/parsing checks that don't need audio hardware:

```
PYTHONPATH=. python tests/test_analysis.py
```

## Project layout

| File | Purpose |
|------|---------|
| `organ_voicing/weighting.py` | A-weighting + RMS/peak level math (numpy only) |
| `organ_voicing/audio.py`     | Mic capture + live metering (sounddevice) |
| `organ_voicing/midi_out.py`  | Send notes to Hauptwerk (mido) |
| `organ_voicing/notes.py`     | Note number/name parsing (pure) |
| `organ_voicing/app.py`       | Tkinter GUI |
| `main.py`                    | Entry point |
