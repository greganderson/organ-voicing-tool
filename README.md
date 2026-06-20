# Organ Voicing Tool

Measure and balance per-note loudness for a Hauptwerk sampleset, using a
measurement mic at your listening position so the result reflects *your room*.

This repo now has **Level 1 (live meter)**, **Level 2 (rank scanner)**, and
**Level 3 (closed-loop auto-voicer)** that writes corrections back into
Hauptwerk by itself.

## Level 1 — Single note tab

- **Live A-weighted loudness meter** from your mic input.
- **Noise floor** measurement at the listening position.
- **Single-note steady-state loudness** as a repeatable dBFS number (skips the
  attack transient so the reading is stable).
- Optionally **fires the note into Hauptwerk over MIDI** so measuring is
  hands-free.
- Logs measurements and **exports CSV**.

## Level 2 — Rank scan tab

- **Unattended scan** of a note range: MIDI-plays each note, measures it,
  optionally averages repeats, and leaves a gap so the room/reverb tail decays
  before the next note.
- Fits a **smooth regulation curve** (outlier-resistant median smoothing — one
  hot pipe can't drag the curve) and **flags notes that deviate** from their
  neighbours beyond your tolerance.
- Shows a **chart** (measured points vs. the target curve, with a tolerance band
  and outliers labelled in red) and a **per-note correction table**: how many dB
  to turn each pipe up (+) or down (−) to sit on the curve.
- Adjust **Smoothing** / **Tolerance** to re-analyze instantly without rescanning.
- **Exports CSV** with measured / target / correction per note.

The numbers are *relative* (dBFS, 0 = digital full scale). For voicing we only
compare notes to each other, so absolute calibration isn't needed.

### Typical scan workflow

1. In Hauptwerk, **solo a single stop** on one manual (draw only that stop).
2. In the app: **Start** the mic, **Open** the MIDI port, set **Channel** to that
   manual's channel, and **Measure noise floor**.
3. Go to the **Rank scan** tab, set the range (e.g. C2–C7), and click **Scan rank**.
4. Read the chart/table, then apply the suggested corrections in Hauptwerk's
   pipe-by-pipe voicing screen. Re-scan to confirm.

## Level 3 — Auto-voice (closed loop)

Found on the **Rank scan** tab. It runs the whole loop hands-free:

> scan → fit target → compute per-note corrections → **type them into Hauptwerk's
> voicing screen** → re-scan → repeat until the rank is within tolerance.

It drives the **amplitude (dB)** fields by keyboard + clipboard (no mouse/pixel
hunting): it reads each field (Ctrl+C), adds the correction, pastes the result
(Ctrl+V), and Tabs to the next note (4 Tabs, or 6 at a B→C octave boundary).
Because it *reads then adds*, it preserves any existing voicing.

**Direction alternates** so focus is never repositioned: the first pass goes
low→high and ends on the top note; the next starts there and goes high→low
(Shift+Tab); and so on. **You only click the starting field once.**

**Self-verifying:** after each apply pass it re-measures and checks the result
matches its prediction. If the numbers don't line up (e.g. a Tab mis-count), it
**stops immediately** rather than writing values to the wrong notes.

### Auto-voice setup

1. In Hauptwerk: solo the stop, open **Organ settings → Pipe and rank voicing**,
   select the rank, and choose **"amplitude (dB)"** in the Adjustment dropdown.
2. **Work in a spare voicing preset** so you can revert / A/B.
3. In the app (Rank scan tab): set the range and **Target** (`smooth` keeps the
   rank's natural regulation curve; `flat` makes every note equal).
4. Click **Start auto-voice**, confirm the prompt. When it says *"click the
   bottom note's amplitude field"*, click that field in Hauptwerk **once** and
   **don't touch the keyboard/mouse** during the apply passes (later passes
   continue automatically in alternating directions).
5. Watch the log: spread and worst-correction shrink each pass until it converges.

**Aborting:** slam the mouse pointer into a screen corner (pyautogui failsafe),
or click **Stop**.

**Tabs/note** and **Tabs at C** are adjustable in case a rank navigates
differently — the self-verification will tell you if they're wrong.

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
| `organ_voicing/scanner.py`   | Unattended rank-scan engine |
| `organ_voicing/analysis.py`  | Regulation-curve fit + outlier detection (numpy only) |
| `organ_voicing/voicing_apply.py` | Keyboard/clipboard automation of Hauptwerk's voicing screen |
| `organ_voicing/notes.py`     | Note number/name parsing (pure) |
| `organ_voicing/app.py`       | Tkinter GUI (Single note + Rank scan tabs) |
| `main.py`                    | Entry point |
