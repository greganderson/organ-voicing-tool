"""MIDI output — play notes into Hauptwerk through a virtual/real MIDI port.

Level 1 only needs to fire a single note on demand (so you can measure it
hands-free). The same helper will drive the unattended rank scanner in Level 2.
"""

from __future__ import annotations

import threading
import time

import mido

from .notes import note_name  # re-exported for callers/back-compat


def list_output_ports() -> list[str]:
    try:
        return list(mido.get_output_names())
    except Exception:
        return []


class MidiPlayer:
    def __init__(self):
        self._port: mido.ports.BaseOutput | None = None
        self._port_name: str | None = None

    def open(self, port_name: str) -> None:
        self.close()
        self._port = mido.open_output(port_name)
        self._port_name = port_name

    def close(self) -> None:
        if self._port is not None:
            try:
                self._port.close()
            finally:
                self._port = None
                self._port_name = None

    @property
    def is_open(self) -> bool:
        return self._port is not None

    @property
    def port_name(self) -> str | None:
        return self._port_name

    def play_note(self, note: int, velocity: int = 100, channel: int = 0,
                  duration_s: float = 2.0, blocking: bool = False) -> None:
        """Send note-on, hold, then note-off.

        With blocking=False the hold happens on a background thread so the GUI
        stays responsive while a measurement runs in parallel.
        """
        if self._port is None:
            raise RuntimeError("No MIDI output port is open.")

        def _run():
            assert self._port is not None
            self._port.send(mido.Message("note_on", note=note, velocity=velocity, channel=channel))
            time.sleep(duration_s)
            self._port.send(mido.Message("note_off", note=note, velocity=0, channel=channel))

        if blocking:
            _run()
        else:
            threading.Thread(target=_run, daemon=True).start()

    def all_notes_off(self, channel: int = 0) -> None:
        if self._port is None:
            return
        # CC 123 = All Notes Off; also blanket note-offs as a fallback.
        self._port.send(mido.Message("control_change", control=123, value=0, channel=channel))
