"""Level 1 — live loudness meter GUI.

Goals for this stage:
  * confirm the measurement mic works on your PC and shows a sane level,
  * see the noise floor at your listening position,
  * measure a single note's steady-state loudness as a repeatable number,
  * optionally fire that note into Hauptwerk over MIDI so it's hands-free.

Everything here is the foundation for the Level 2 unattended rank scanner.
"""

from __future__ import annotations

import csv
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import audio, midi_out, weighting
from .notes import parse_note


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Organ Voicing Tool — Live Meter (Level 1)")
        self.geometry("760x620")
        self.minsize(680, 560)

        self.meter = audio.AudioMeter()
        self.player = midi_out.MidiPlayer()
        self.noise_floor_db: float | None = None
        self._busy = False

        self._build_ui()
        self._refresh_devices()
        self._tick()  # start live-meter update loop
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ----- UI construction --------------------------------------------------

    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- Input device row ---
        dev = ttk.LabelFrame(self, text="Microphone input")
        dev.pack(fill="x", **pad)
        self.device_cb = ttk.Combobox(dev, state="readonly", width=48)
        self.device_cb.grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(dev, text="Refresh", command=self._refresh_devices).grid(row=0, column=1, padx=4)
        self.start_btn = ttk.Button(dev, text="Start", command=self._toggle_stream)
        self.start_btn.grid(row=0, column=2, padx=4)
        self.stream_status = ttk.Label(dev, text="stopped", foreground="#a00")
        self.stream_status.grid(row=0, column=3, padx=8)

        # --- Live meter ---
        meterf = ttk.LabelFrame(self, text="Live level (A-weighted)")
        meterf.pack(fill="x", **pad)
        self.canvas = tk.Canvas(meterf, height=46, bg="#111", highlightthickness=0)
        self.canvas.pack(fill="x", padx=8, pady=(8, 2))
        info = ttk.Frame(meterf)
        info.pack(fill="x", padx=8, pady=(0, 8))
        self.live_lbl = ttk.Label(info, text="—  dBFS", font=("Consolas", 16, "bold"))
        self.live_lbl.pack(side="left")
        self.peak_lbl = ttk.Label(info, text="peak —", foreground="#666")
        self.peak_lbl.pack(side="left", padx=16)
        self.clip_lbl = ttk.Label(info, text="", foreground="#c00", font=("", 10, "bold"))
        self.clip_lbl.pack(side="left", padx=8)

        # --- Noise floor ---
        nf = ttk.LabelFrame(self, text="Noise floor")
        nf.pack(fill="x", **pad)
        ttk.Button(nf, text="Measure noise floor (stay quiet ~2 s)",
                   command=self._measure_noise_floor).grid(row=0, column=0, padx=6, pady=6)
        self.noise_lbl = ttk.Label(nf, text="not measured")
        self.noise_lbl.grid(row=0, column=1, padx=8)

        # --- MIDI + measurement ---
        m = ttk.LabelFrame(self, text="Measure a note")
        m.pack(fill="x", **pad)

        ttk.Label(m, text="MIDI out:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.midi_cb = ttk.Combobox(m, state="readonly", width=30)
        self.midi_cb.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(m, text="Open", command=self._open_midi).grid(row=0, column=2, padx=4)
        self.midi_status = ttk.Label(m, text="closed", foreground="#a00")
        self.midi_status.grid(row=0, column=3, padx=6, sticky="w")

        ttk.Label(m, text="Note:").grid(row=1, column=0, sticky="e", padx=4)
        self.note_var = tk.StringVar(value="C4")
        ttk.Entry(m, textvariable=self.note_var, width=8).grid(row=1, column=1, sticky="w", padx=4)
        ttk.Label(m, text="Channel:").grid(row=1, column=2, sticky="e")
        self.chan_var = tk.IntVar(value=1)
        ttk.Spinbox(m, from_=1, to=16, textvariable=self.chan_var, width=4).grid(row=1, column=3, sticky="w")

        ttk.Label(m, text="Velocity:").grid(row=2, column=0, sticky="e", padx=4)
        self.vel_var = tk.IntVar(value=100)
        ttk.Spinbox(m, from_=1, to=127, textvariable=self.vel_var, width=5).grid(row=2, column=1, sticky="w", padx=4)
        ttk.Label(m, text="Duration (s):").grid(row=2, column=2, sticky="e")
        self.dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(m, from_=0.5, to=10, increment=0.5, textvariable=self.dur_var, width=5).grid(row=2, column=3, sticky="w")

        btns = ttk.Frame(m)
        btns.grid(row=3, column=0, columnspan=4, pady=8, sticky="w", padx=4)
        self.play_btn = ttk.Button(btns, text="▶ Play note + measure", command=self._play_and_measure)
        self.play_btn.pack(side="left", padx=4)
        self.meas_btn = ttk.Button(btns, text="Measure (I'll play it)", command=self._measure_only)
        self.meas_btn.pack(side="left", padx=4)

        # --- History table ---
        hist = ttk.LabelFrame(self, text="Measurements")
        hist.pack(fill="both", expand=True, **pad)
        cols = ("note", "loud", "peak", "snr")
        self.tree = ttk.Treeview(hist, columns=cols, show="headings", height=8)
        for c, txt, w in (("note", "Note", 80), ("loud", "A-wt dBFS", 110),
                          ("peak", "Peak dBFS", 110), ("snr", "Above noise (dB)", 130)):
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(hist, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y", pady=8)
        self.tree.configure(yscrollcommand=sb.set)
        side = ttk.Frame(hist)
        side.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(side, text="Clear", command=lambda: self.tree.delete(*self.tree.get_children())).pack(fill="x", pady=2)
        ttk.Button(side, text="Export CSV…", command=self._export_csv).pack(fill="x", pady=2)

    # ----- device / port handling ------------------------------------------

    def _refresh_devices(self):
        self._input_devices = audio.list_input_devices()
        self.device_cb["values"] = [f"[{d.index}] {d.name}" for d in self._input_devices]
        if self._input_devices and not self.device_cb.get():
            self.device_cb.current(0)
        ports = midi_out.list_output_ports()
        self.midi_cb["values"] = ports
        if ports and not self.midi_cb.get():
            self.midi_cb.current(0)

    def _selected_device_index(self) -> int | None:
        sel = self.device_cb.current()
        if sel < 0 or sel >= len(self._input_devices):
            return None
        return self._input_devices[sel].index

    def _toggle_stream(self):
        if self.meter.running:
            self.meter.stop()
            self.start_btn.config(text="Start")
            self.stream_status.config(text="stopped", foreground="#a00")
            return
        idx = self._selected_device_index()
        if idx is None:
            messagebox.showwarning("No device", "Pick a microphone input first.")
            return
        try:
            self.meter.start(idx)
        except Exception as e:
            messagebox.showerror("Audio error", f"Couldn't open the input device:\n{e}")
            return
        self.start_btn.config(text="Stop")
        self.stream_status.config(text=f"running @ {self.meter.samplerate} Hz", foreground="#080")

    def _open_midi(self):
        name = self.midi_cb.get()
        if not name:
            messagebox.showwarning("No MIDI port", "No MIDI output ports found.\n"
                                   "Start loopMIDI (or your interface) and click Refresh.")
            return
        try:
            self.player.open(name)
        except Exception as e:
            messagebox.showerror("MIDI error", f"Couldn't open MIDI port:\n{e}")
            return
        self.midi_status.config(text="open", foreground="#080")

    # ----- measurement actions ---------------------------------------------

    def _measure_noise_floor(self):
        if not self.meter.running:
            messagebox.showwarning("Not running", "Start the microphone first.")
            return
        self._run_async(self._do_noise_floor)

    def _do_noise_floor(self):
        m = self.meter.capture(duration_s=2.0, skip_attack_s=0.2)
        self.noise_floor_db = m.a_weighted_db
        self.after(0, lambda: self.noise_lbl.config(
            text=f"{self.noise_floor_db:6.1f} dBFS  (A-weighted)"))

    def _measure_only(self):
        if not self.meter.running:
            messagebox.showwarning("Not running", "Start the microphone first.")
            return
        dur = float(self.dur_var.get())
        self._run_async(lambda: self._do_measure(label=None, duration=dur))

    def _play_and_measure(self):
        if not self.meter.running:
            messagebox.showwarning("Not running", "Start the microphone first.")
            return
        if not self.player.is_open:
            messagebox.showwarning("No MIDI", "Open a MIDI output port first.")
            return
        try:
            note = parse_note(self.note_var.get())
        except ValueError as e:
            messagebox.showerror("Bad note", str(e))
            return
        dur = float(self.dur_var.get())
        chan = int(self.chan_var.get()) - 1
        vel = int(self.vel_var.get())

        def task():
            # Hold the note a touch longer than the capture so it sustains
            # through the whole measurement window.
            self.player.play_note(note, velocity=vel, channel=chan,
                                  duration_s=dur + 0.4, blocking=False)
            time.sleep(0.05)
            self._do_measure(label=midi_out.note_name(note), duration=dur)

        self._run_async(task)

    def _do_measure(self, label: str | None, duration: float):
        m = self.meter.capture(duration_s=duration, skip_attack_s=0.3)
        name = label or "(manual)"
        snr = (m.a_weighted_db - self.noise_floor_db) if self.noise_floor_db is not None else None
        self.after(0, lambda: self._add_row(name, m, snr))

    def _add_row(self, name, m: audio.Measurement, snr):
        snr_txt = f"{snr:+.1f}" if snr is not None else "—"
        self.tree.insert("", 0, values=(name, f"{m.a_weighted_db:.1f}",
                                        f"{m.peak_db:.1f}", snr_txt))

    # ----- async helper (keeps GUI responsive during a ~2 s capture) --------

    def _run_async(self, fn):
        if self._busy:
            return
        self._busy = True
        self._set_buttons(False)

        def wrapper():
            try:
                fn()
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
            finally:
                self.after(0, self._done_async)

        threading.Thread(target=wrapper, daemon=True).start()

    def _done_async(self):
        self._busy = False
        self._set_buttons(True)

    def _set_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for b in (self.play_btn, self.meas_btn):
            b.config(state=state)

    # ----- export -----------------------------------------------------------

    def _export_csv(self):
        rows = [self.tree.item(i)["values"] for i in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("Nothing to export", "No measurements yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["note", "a_weighted_dbfs", "peak_dbfs", "above_noise_db"])
            for r in reversed(rows):  # oldest first
                w.writerow(r)

    # ----- live meter loop --------------------------------------------------

    def _tick(self):
        if self.meter.running:
            db, pk = self.meter.live_level()
            self._draw_meter(db, pk)
            self.live_lbl.config(text=f"{db:6.1f} dBFS")
            self.peak_lbl.config(text=f"peak {pk:5.1f}")
            self.clip_lbl.config(text="CLIP!" if pk > -0.5 else "")
        self.after(50, self._tick)

    def _draw_meter(self, db: float, pk: float):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 700
        h = c.winfo_height() or 46
        # Map -80..0 dBFS to 0..w
        lo, hi = -80.0, 0.0
        frac = max(0.0, min(1.0, (db - lo) / (hi - lo)))
        bar_w = int(frac * w)
        # Colour: green low, yellow mid, red near clip.
        color = "#2ecc40" if db < -18 else ("#ffdc00" if db < -6 else "#ff4136")
        c.create_rectangle(0, 0, bar_w, h, fill=color, width=0)
        # Noise-floor marker.
        if self.noise_floor_db is not None:
            nf = max(0.0, min(1.0, (self.noise_floor_db - lo) / (hi - lo)))
            x = int(nf * w)
            c.create_line(x, 0, x, h, fill="#888", dash=(3, 2))
        # Gridlines every 20 dB.
        for mark in (-60, -40, -20):
            x = int((mark - lo) / (hi - lo) * w)
            c.create_line(x, 0, x, h, fill="#333")
            c.create_text(x + 2, h - 8, text=f"{mark}", anchor="w", fill="#666", font=("", 7))

    def _on_close(self):
        try:
            self.meter.stop()
            self.player.close()
        finally:
            self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
