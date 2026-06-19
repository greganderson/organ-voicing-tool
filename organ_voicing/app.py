"""Organ Voicing Tool GUI.

Tab 1 — Single note: the Level 1 live meter + one-note measurement (also the
        place to set up and sanity-check the mic/MIDI chain).
Tab 2 — Rank scan:   the Level 2 unattended scanner. Solo a stop, set the range,
        hit Scan; it walks the rank, fits a smooth regulation curve, flags
        outliers, and gives a per-note correction in dB.
"""

from __future__ import annotations

import csv
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from . import analysis, audio, midi_out, scanner, weighting
from .notes import note_name, parse_note


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Organ Voicing Tool")
        self.geometry("900x760")
        self.minsize(820, 680)

        self.meter = audio.AudioMeter()
        self.player = midi_out.MidiPlayer()
        self.noise_floor_db: float | None = None
        self._busy = False
        self._scan_stop = False
        self._scan_results: list[scanner.NoteResult] = []
        self._balance: analysis.BalanceResult | None = None

        self._build_shared()
        self._build_notebook()
        self._refresh_devices()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ===== shared top section ==============================================

    def _build_shared(self):
        pad = {"padx": 8, "pady": 4}

        dev = ttk.LabelFrame(self, text="Microphone input")
        dev.pack(fill="x", **pad)
        self.device_cb = ttk.Combobox(dev, state="readonly", width=46)
        self.device_cb.grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(dev, text="Refresh", command=self._refresh_devices).grid(row=0, column=1, padx=4)
        self.start_btn = ttk.Button(dev, text="Start", command=self._toggle_stream)
        self.start_btn.grid(row=0, column=2, padx=4)
        self.stream_status = ttk.Label(dev, text="stopped", foreground="#a00")
        self.stream_status.grid(row=0, column=3, padx=8)

        meterf = ttk.LabelFrame(self, text="Live level (A-weighted)")
        meterf.pack(fill="x", **pad)
        self.canvas = tk.Canvas(meterf, height=42, bg="#111", highlightthickness=0)
        self.canvas.pack(fill="x", padx=8, pady=(8, 2))
        info = ttk.Frame(meterf)
        info.pack(fill="x", padx=8, pady=(0, 8))
        self.live_lbl = ttk.Label(info, text="—  dBFS", font=("Consolas", 15, "bold"))
        self.live_lbl.pack(side="left")
        self.peak_lbl = ttk.Label(info, text="peak —", foreground="#666")
        self.peak_lbl.pack(side="left", padx=16)
        self.clip_lbl = ttk.Label(info, text="", foreground="#c00", font=("", 10, "bold"))
        self.clip_lbl.pack(side="left", padx=8)
        ttk.Button(info, text="Measure noise floor", command=self._measure_noise_floor).pack(side="right")
        self.noise_lbl = ttk.Label(info, text="noise floor: not measured", foreground="#666")
        self.noise_lbl.pack(side="right", padx=10)

        # Shared MIDI port + per-note MIDI params used by both tabs.
        m = ttk.LabelFrame(self, text="MIDI to Hauptwerk")
        m.pack(fill="x", **pad)
        ttk.Label(m, text="Port:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.midi_cb = ttk.Combobox(m, state="readonly", width=28)
        self.midi_cb.grid(row=0, column=1, padx=4, sticky="w")
        ttk.Button(m, text="Open", command=self._open_midi).grid(row=0, column=2, padx=4)
        self.midi_status = ttk.Label(m, text="closed", foreground="#a00")
        self.midi_status.grid(row=0, column=3, padx=6, sticky="w")
        ttk.Label(m, text="Channel:").grid(row=0, column=4, sticky="e", padx=(16, 2))
        self.chan_var = tk.IntVar(value=9)
        ttk.Spinbox(m, from_=1, to=16, textvariable=self.chan_var, width=4).grid(row=0, column=5, sticky="w")
        ttk.Label(m, text="Velocity:").grid(row=0, column=6, sticky="e", padx=(16, 2))
        self.vel_var = tk.IntVar(value=100)
        ttk.Spinbox(m, from_=1, to=127, textvariable=self.vel_var, width=5).grid(row=0, column=7, sticky="w")

    def _build_notebook(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=6)
        self._build_single_tab(nb)
        self._build_scan_tab(nb)

    # ===== Tab 1: single note ==============================================

    def _build_single_tab(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Single note")

        c = ttk.Frame(tab)
        c.pack(fill="x", padx=6, pady=8)
        ttk.Label(c, text="Note:").grid(row=0, column=0, sticky="e", padx=4)
        self.note_var = tk.StringVar(value="C4")
        ttk.Entry(c, textvariable=self.note_var, width=8).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Label(c, text="Duration (s):").grid(row=0, column=2, sticky="e", padx=(16, 2))
        self.dur_var = tk.DoubleVar(value=2.0)
        ttk.Spinbox(c, from_=0.5, to=10, increment=0.5, textvariable=self.dur_var, width=5).grid(row=0, column=3, sticky="w")
        self.play_btn = ttk.Button(c, text="▶ Play note + measure", command=self._play_and_measure)
        self.play_btn.grid(row=0, column=4, padx=(16, 4))
        self.meas_btn = ttk.Button(c, text="Measure (I'll play it)", command=self._measure_only)
        self.meas_btn.grid(row=0, column=5, padx=4)

        hist = ttk.LabelFrame(tab, text="Measurements")
        hist.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("note", "loud", "peak", "snr")
        self.tree = ttk.Treeview(hist, columns=cols, show="headings", height=8)
        for c_, txt, w in (("note", "Note", 80), ("loud", "A-wt dBFS", 110),
                           ("peak", "Peak dBFS", 110), ("snr", "Above noise (dB)", 130)):
            self.tree.heading(c_, text=txt)
            self.tree.column(c_, width=w, anchor="center")
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(hist, orient="vertical", command=self.tree.yview)
        sb.pack(side="left", fill="y", pady=8)
        self.tree.configure(yscrollcommand=sb.set)
        side = ttk.Frame(hist)
        side.pack(side="left", fill="y", padx=8, pady=8)
        ttk.Button(side, text="Clear", command=lambda: self.tree.delete(*self.tree.get_children())).pack(fill="x", pady=2)
        ttk.Button(side, text="Export CSV…", command=self._export_single_csv).pack(fill="x", pady=2)

    # ===== Tab 2: rank scan ================================================

    def _build_scan_tab(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Rank scan")

        opt = ttk.LabelFrame(tab, text="Scan settings")
        opt.pack(fill="x", padx=6, pady=6)
        # Row 0: range
        ttk.Label(opt, text="From:").grid(row=0, column=0, sticky="e", padx=4, pady=4)
        self.low_var = tk.StringVar(value="C2")
        ttk.Entry(opt, textvariable=self.low_var, width=7).grid(row=0, column=1, sticky="w")
        ttk.Label(opt, text="To:").grid(row=0, column=2, sticky="e", padx=4)
        self.high_var = tk.StringVar(value="C7")
        ttk.Entry(opt, textvariable=self.high_var, width=7).grid(row=0, column=3, sticky="w")
        # Row 0 cont: timing
        ttk.Label(opt, text="Note dur (s):").grid(row=0, column=4, sticky="e", padx=(16, 2))
        self.sdur_var = tk.DoubleVar(value=1.5)
        ttk.Spinbox(opt, from_=0.5, to=6, increment=0.5, textvariable=self.sdur_var, width=5).grid(row=0, column=5, sticky="w")
        ttk.Label(opt, text="Gap (s):").grid(row=0, column=6, sticky="e", padx=(16, 2))
        self.gap_var = tk.DoubleVar(value=0.6)
        ttk.Spinbox(opt, from_=0.0, to=4, increment=0.1, textvariable=self.gap_var, width=5).grid(row=0, column=7, sticky="w")
        ttk.Label(opt, text="Repeats:").grid(row=0, column=8, sticky="e", padx=(16, 2))
        self.rep_var = tk.IntVar(value=1)
        ttk.Spinbox(opt, from_=1, to=5, textvariable=self.rep_var, width=4).grid(row=0, column=9, sticky="w")
        # Row 1: analysis params
        ttk.Label(opt, text="Smoothing:").grid(row=1, column=0, sticky="e", padx=4, pady=4)
        self.win_var = tk.IntVar(value=7)
        ttk.Spinbox(opt, from_=3, to=21, increment=2, textvariable=self.win_var, width=4,
                    command=self._reanalyze).grid(row=1, column=1, sticky="w")
        ttk.Label(opt, text="Tolerance (dB):").grid(row=1, column=2, sticky="e", padx=4)
        self.tol_var = tk.DoubleVar(value=1.5)
        ttk.Spinbox(opt, from_=0.5, to=6, increment=0.5, textvariable=self.tol_var, width=5,
                    command=self._reanalyze).grid(row=1, column=3, sticky="w")
        self.scan_btn = ttk.Button(opt, text="▶ Scan rank", command=self._start_scan)
        self.scan_btn.grid(row=1, column=5, padx=(16, 4), pady=4)
        self.stop_btn = ttk.Button(opt, text="Stop", command=self._stop_scan, state="disabled")
        self.stop_btn.grid(row=1, column=6, padx=4)
        ttk.Button(opt, text="Export CSV…", command=self._export_scan_csv).grid(row=1, column=7, padx=4)

        prog = ttk.Frame(tab)
        prog.pack(fill="x", padx=6)
        self.scan_pb = ttk.Progressbar(prog, mode="determinate")
        self.scan_pb.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.scan_status = ttk.Label(prog, text="idle")
        self.scan_status.pack(side="left")

        # Chart
        chartf = ttk.LabelFrame(tab, text="Loudness across the rank")
        chartf.pack(fill="x", padx=6, pady=6)
        self.chart = tk.Canvas(chartf, height=240, bg="#fbfbfb", highlightthickness=1,
                               highlightbackground="#ccc")
        self.chart.pack(fill="x", padx=8, pady=8)
        self.chart.bind("<Configure>", lambda e: self._draw_chart())

        # Results table
        resf = ttk.LabelFrame(tab, text="Per-note corrections")
        resf.pack(fill="both", expand=True, padx=6, pady=6)
        cols = ("note", "meas", "target", "corr", "flag")
        self.scan_tree = ttk.Treeview(resf, columns=cols, show="headings", height=8)
        for c_, txt, w in (("note", "Note", 70), ("meas", "Measured dB", 110),
                           ("target", "Target dB", 100), ("corr", "Correction dB", 120),
                           ("flag", "Flag", 120)):
            self.scan_tree.heading(c_, text=txt)
            self.scan_tree.column(c_, width=w, anchor="center")
        self.scan_tree.tag_configure("outlier", background="#ffe0e0")
        self.scan_tree.tag_configure("warn", background="#fff3cd")
        self.scan_tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(resf, orient="vertical", command=self.scan_tree.yview)
        sb.pack(side="left", fill="y", pady=8)
        self.scan_tree.configure(yscrollcommand=sb.set)

    # ===== device / port handling ==========================================

    def _refresh_devices(self):
        self._input_devices = audio.list_input_devices()
        self.device_cb["values"] = [f"[{d.index}] {d.name}" for d in self._input_devices]
        if self._input_devices and not self.device_cb.get():
            self.device_cb.current(0)
        ports = midi_out.list_output_ports()
        self.midi_cb["values"] = ports
        if ports and not self.midi_cb.get():
            self.midi_cb.current(0)

    def _selected_device_index(self):
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

    def _channel(self):
        return int(self.chan_var.get()) - 1

    # ===== noise floor + single-note measurement ===========================

    def _measure_noise_floor(self):
        if not self._require_stream():
            return
        self._run_async(self._do_noise_floor)

    def _do_noise_floor(self):
        m = self.meter.capture(duration_s=2.0, skip_attack_s=0.2)
        self.noise_floor_db = m.a_weighted_db
        self.after(0, lambda: self.noise_lbl.config(
            text=f"noise floor: {self.noise_floor_db:.1f} dBFS", foreground="#333"))

    def _measure_only(self):
        if not self._require_stream():
            return
        dur = float(self.dur_var.get())
        self._run_async(lambda: self._do_measure(None, dur))

    def _play_and_measure(self):
        if not self._require_stream() or not self._require_midi():
            return
        try:
            note = parse_note(self.note_var.get())
        except ValueError as e:
            messagebox.showerror("Bad note", str(e))
            return
        dur = float(self.dur_var.get())
        chan, vel = self._channel(), int(self.vel_var.get())

        def task():
            self.player.play_note(note, velocity=vel, channel=chan,
                                  duration_s=dur + 0.4, blocking=False)
            time.sleep(0.05)
            self._do_measure(note_name(note), dur)

        self._run_async(task)

    def _do_measure(self, label, duration):
        m = self.meter.capture(duration_s=duration, skip_attack_s=0.3)
        name = label or "(manual)"
        snr = (m.a_weighted_db - self.noise_floor_db) if self.noise_floor_db is not None else None
        self.after(0, lambda: self._add_single_row(name, m, snr))

    def _add_single_row(self, name, m, snr):
        snr_txt = f"{snr:+.1f}" if snr is not None else "—"
        self.tree.insert("", 0, values=(name, f"{m.a_weighted_db:.1f}",
                                        f"{m.peak_db:.1f}", snr_txt))

    # ===== rank scan ========================================================

    def _start_scan(self):
        if self._busy or not self._require_stream() or not self._require_midi():
            return
        try:
            low, high = parse_note(self.low_var.get()), parse_note(self.high_var.get())
        except ValueError as e:
            messagebox.showerror("Bad note range", str(e))
            return
        if high < low:
            messagebox.showerror("Bad range", "'To' note must be ≥ 'From' note.")
            return

        total = high - low + 1
        est = total * self.rep_var.get() * (self.sdur_var.get() + self.gap_var.get() + 0.45)
        self.scan_tree.delete(*self.scan_tree.get_children())
        self._scan_results = []
        self._balance = None
        self._scan_stop = False
        self.scan_pb.config(maximum=total, value=0)
        self.scan_status.config(text=f"0 / {total}   (~{est/60:.1f} min)")
        self._busy = True
        self._set_scan_running(True)

        params = dict(
            channel=self._channel(), velocity=int(self.vel_var.get()),
            duration_s=float(self.sdur_var.get()), gap_s=float(self.gap_var.get()),
            repeats=int(self.rep_var.get()), noise_floor_db=self.noise_floor_db,
        )

        def progress(done, total_, res):
            self.after(0, lambda: self._on_scan_progress(done, total_, res))

        def worker():
            try:
                scanner.scan_rank(
                    self.meter, self.player, low, high,
                    should_stop=lambda: self._scan_stop,
                    on_progress=progress, **params,
                )
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Scan error", str(e)))
            finally:
                self.after(0, self._on_scan_done)

        threading.Thread(target=worker, daemon=True).start()

    def _on_scan_progress(self, done, total, res: scanner.NoteResult):
        self._scan_results.append(res)
        self.scan_pb.config(value=done)
        self.scan_status.config(text=f"{done} / {total}   (now {res.name})")

    def _stop_scan(self):
        self._scan_stop = True
        self.scan_status.config(text="stopping…")

    def _on_scan_done(self):
        self._busy = False
        self._set_scan_running(False)
        n = len(self._scan_results)
        self.scan_status.config(text=f"done — {n} notes")
        if n >= 3:
            self._reanalyze()

    def _set_scan_running(self, running):
        self.scan_btn.config(state="disabled" if running else "normal")
        self.stop_btn.config(state="normal" if running else "disabled")
        for b in (self.play_btn, self.meas_btn):
            b.config(state="disabled" if running else "normal")

    def _reanalyze(self):
        """Recompute curve/outliers from current results (cheap; re-run on slider change)."""
        if len(self._scan_results) < 3:
            return
        values = [r.a_weighted_db for r in self._scan_results]
        self._balance = analysis.analyze(
            values, window=int(self.win_var.get()), tolerance_db=float(self.tol_var.get()))
        self._populate_scan_table()
        self._draw_chart()

    def _populate_scan_table(self):
        self.scan_tree.delete(*self.scan_tree.get_children())
        b = self._balance
        for i, r in enumerate(self._scan_results):
            corr = b.correction[i]
            flags = []
            tag = ""
            if b.is_outlier[i]:
                flags.append("OUTLIER")
                tag = "outlier"
            if r.clipped:
                flags.append("clip")
            if r.low_snr:
                flags.append("low SNR")
            if flags and not tag:
                tag = "warn"
            self.scan_tree.insert("", "end", tags=(tag,) if tag else (),
                                  values=(r.name, f"{r.a_weighted_db:.1f}",
                                          f"{b.target[i]:.1f}", f"{corr:+.1f}",
                                          ", ".join(flags)))

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        results, b = self._scan_results, self._balance
        if len(results) < 2 or b is None:
            c.create_text(c.winfo_width() // 2 or 200, c.winfo_height() // 2 or 100,
                          text="Scan a rank to see the curve", fill="#999")
            return
        W = c.winfo_width() or 800
        H = c.winfo_height() or 240
        ml, mr, mt, mb = 46, 14, 14, 24
        pw, ph = W - ml - mr, H - mt - mb

        meas = np.array([r.a_weighted_db for r in results])
        tgt = b.target
        ymin = float(min(meas.min(), tgt.min())) - 1.0
        ymax = float(max(meas.max(), tgt.max())) + 1.0
        if ymax - ymin < 1e-6:
            ymax += 1.0
        n = len(results)

        def X(i):
            return ml + (pw * i / (n - 1) if n > 1 else pw / 2)

        def Y(v):
            return mt + ph * (1 - (v - ymin) / (ymax - ymin))

        # y gridlines + labels
        for k in range(5):
            v = ymin + (ymax - ymin) * k / 4
            y = Y(v)
            c.create_line(ml, y, W - mr, y, fill="#eee")
            c.create_text(ml - 6, y, text=f"{v:.0f}", anchor="e", fill="#888", font=("", 8))

        # tolerance band around target
        tol = float(self.tol_var.get())
        band = []
        for i in range(n):
            band.append((X(i), Y(tgt[i] + tol)))
        for i in range(n - 1, -1, -1):
            band.append((X(i), Y(tgt[i] - tol)))
        if len(band) >= 3:
            c.create_polygon(band, fill="#eaf3ff", outline="")

        # target curve
        tline = [coord for i in range(n) for coord in (X(i), Y(tgt[i]))]
        if len(tline) >= 4:
            c.create_line(tline, fill="#3b82f6", width=2, smooth=True)

        # measured points
        for i, r in enumerate(results):
            x, y = X(i), Y(meas[i])
            if b.is_outlier[i]:
                c.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#ff4136", outline="")
                c.create_text(x, y - 9, text=r.name, fill="#c00", font=("", 7))
            else:
                c.create_oval(x - 2.5, y - 2.5, x + 2.5, y + 2.5, fill="#2ecc40", outline="")

        # x end labels
        c.create_text(X(0), H - mb + 12, text=results[0].name, fill="#888", font=("", 8))
        c.create_text(X(n - 1), H - mb + 12, text=results[-1].name, fill="#888", font=("", 8))
        c.create_text(W - mr, mt + 4, anchor="ne", fill="#666", font=("", 8),
                      text=f"spread {b.spread_db:.1f} dB · σ {b.residual_std_db:.1f} dB · "
                           f"{int(b.is_outlier.sum())} outliers")

    # ===== async helper =====================================================

    def _require_stream(self):
        if not self.meter.running:
            messagebox.showwarning("Not running", "Start the microphone first.")
            return False
        return True

    def _require_midi(self):
        if not self.player.is_open:
            messagebox.showwarning("No MIDI", "Open a MIDI output port first.")
            return False
        return True

    def _run_async(self, fn):
        if self._busy:
            return
        self._busy = True
        self._set_single_buttons(False)

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
        self._set_single_buttons(True)

    def _set_single_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for b in (self.play_btn, self.meas_btn):
            b.config(state=state)

    # ===== export ===========================================================

    def _export_single_csv(self):
        rows = [self.tree.item(i)["values"] for i in self.tree.get_children()]
        if not rows:
            messagebox.showinfo("Nothing to export", "No measurements yet.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["note", "a_weighted_dbfs", "peak_dbfs", "above_noise_db"])
            for r in reversed(rows):
                w.writerow(r)

    def _export_scan_csv(self):
        if not self._scan_results or self._balance is None:
            messagebox.showinfo("Nothing to export", "Run a scan first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        b = self._balance
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["note", "midi", "measured_dbfs", "target_dbfs",
                        "correction_db", "outlier", "peak_dbfs", "above_noise_db"])
            for i, r in enumerate(self._scan_results):
                w.writerow([r.name, r.note, f"{r.a_weighted_db:.2f}", f"{b.target[i]:.2f}",
                            f"{b.correction[i]:+.2f}", int(b.is_outlier[i]),
                            f"{r.peak_db:.2f}",
                            f"{r.snr_db:.2f}" if r.snr_db is not None else ""])

    # ===== live meter loop ==================================================

    def _tick(self):
        if self.meter.running:
            db, pk = self.meter.live_level()
            self._draw_meter(db, pk)
            self.live_lbl.config(text=f"{db:6.1f} dBFS")
            self.peak_lbl.config(text=f"peak {pk:5.1f}")
            self.clip_lbl.config(text="CLIP!" if pk > -0.5 else "")
        self.after(50, self._tick)

    def _draw_meter(self, db, pk):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width() or 700
        h = c.winfo_height() or 42
        lo, hi = -80.0, 0.0
        frac = max(0.0, min(1.0, (db - lo) / (hi - lo)))
        color = "#2ecc40" if db < -18 else ("#ffdc00" if db < -6 else "#ff4136")
        c.create_rectangle(0, 0, int(frac * w), h, fill=color, width=0)
        if self.noise_floor_db is not None:
            x = int((self.noise_floor_db - lo) / (hi - lo) * w)
            c.create_line(x, 0, x, h, fill="#888", dash=(3, 2))
        for mark in (-60, -40, -20):
            x = int((mark - lo) / (hi - lo) * w)
            c.create_line(x, 0, x, h, fill="#333")
            c.create_text(x + 2, h - 8, text=f"{mark}", anchor="w", fill="#666", font=("", 7))

    def _on_close(self):
        self._scan_stop = True
        try:
            self.meter.stop()
            self.player.close()
        finally:
            self.destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
