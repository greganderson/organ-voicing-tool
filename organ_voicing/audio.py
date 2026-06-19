"""Audio input capture and live metering via sounddevice (PortAudio).

Designed for a physical measurement mic at the listening position. The stream
runs continuously; the callback keeps a smoothed live level for the meter and,
when asked, accumulates a fixed-length recording for a single-note measurement.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np
import sounddevice as sd

from . import weighting


@dataclass
class DeviceInfo:
    index: int
    name: str
    channels: int
    default_samplerate: float


def list_input_devices() -> list[DeviceInfo]:
    devices = []
    for i, d in enumerate(sd.query_devices()):
        if d.get("max_input_channels", 0) > 0:
            devices.append(
                DeviceInfo(
                    index=i,
                    name=d["name"],
                    channels=d["max_input_channels"],
                    default_samplerate=d.get("default_samplerate", 48000.0),
                )
            )
    return devices


@dataclass
class Measurement:
    """Result of a single steady-state note measurement."""

    a_weighted_db: float
    peak_db: float
    samplerate: int
    duration_s: float
    skipped_attack_s: float


class AudioMeter:
    """Continuous input stream with a live A-weighted level and on-demand capture."""

    def __init__(self, samplerate: int = 48000, blocksize: int = 4096):
        self.samplerate = samplerate
        self.blocksize = blocksize
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()

        # Live metering (updated every block).
        self._live_db = weighting.MIN_DB
        self._live_peak_db = weighting.MIN_DB

        # Capture state.
        self._capturing = False
        self._capture_buf: list[np.ndarray] = []
        self._capture_target = 0  # samples to collect

    # ----- stream lifecycle -------------------------------------------------

    def start(self, device_index: int) -> None:
        self.stop()
        dev = sd.query_devices(device_index)
        # Use device default rate if it disagrees with ours, to avoid surprises.
        sr = int(dev.get("default_samplerate") or self.samplerate)
        self.samplerate = sr
        self._stream = sd.InputStream(
            device=device_index,
            channels=1,
            samplerate=sr,
            blocksize=self.blocksize,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    @property
    def running(self) -> bool:
        return self._stream is not None and self._stream.active

    # ----- callback ---------------------------------------------------------

    def _callback(self, indata, frames, time_info, status):  # noqa: D401
        # Mono mix (we open 1 channel, but be defensive).
        block = np.asarray(indata, dtype=np.float64)
        if block.ndim > 1:
            block = block.mean(axis=1)

        a_db = weighting.a_weighted_rms(block, self.samplerate)
        pk = weighting.peak_dbfs(block)
        with self._lock:
            self._live_db = a_db
            self._live_peak_db = pk
            if self._capturing:
                self._capture_buf.append(block.copy())
                collected = sum(b.size for b in self._capture_buf)
                if collected >= self._capture_target:
                    self._capturing = False

    # ----- live readout -----------------------------------------------------

    def live_level(self) -> tuple[float, float]:
        """Return (A-weighted dBFS, peak dBFS) of the most recent block."""
        with self._lock:
            return self._live_db, self._live_peak_db

    # ----- single measurement ----------------------------------------------

    def capture(self, duration_s: float, skip_attack_s: float = 0.3) -> Measurement:
        """Record `duration_s` of audio and measure its steady-state portion.

        Blocks until the recording is complete. The first `skip_attack_s` is
        discarded so the pipe's onset transient doesn't bias the level.
        """
        if not self.running:
            raise RuntimeError("Audio stream is not running.")

        with self._lock:
            self._capture_buf = []
            self._capture_target = int(duration_s * self.samplerate)
            self._capturing = True

        # Wait for the callback to finish filling the buffer.
        deadline_blocks = self._capture_target / self.blocksize + 20
        waited = 0
        while True:
            with self._lock:
                done = not self._capturing
            if done:
                break
            sd.sleep(20)
            waited += 1
            if waited > deadline_blocks * 50:  # generous safety timeout
                with self._lock:
                    self._capturing = False
                break

        with self._lock:
            buf = np.concatenate(self._capture_buf) if self._capture_buf else np.zeros(1)

        skip = int(skip_attack_s * self.samplerate)
        steady = buf[skip:] if buf.size > skip else buf
        return Measurement(
            a_weighted_db=weighting.a_weighted_rms(steady, self.samplerate),
            peak_db=weighting.peak_dbfs(buf),
            samplerate=self.samplerate,
            duration_s=buf.size / self.samplerate,
            skipped_attack_s=skip_attack_s,
        )
