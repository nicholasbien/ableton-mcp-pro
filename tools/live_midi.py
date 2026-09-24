"""
The fast path to Ableton Live: MIDI over macOS IAC buses (or any CoreMIDI port), for anything
timed. `live_client.py` (the port-9877 socket) costs 0.4-1.5 s per call and its song-time
readings go stale under load; use it to set things up, use this to play and to follow Live's
clock.

    import sys; sys.path.insert(0, "path/to/ableton-mcp-pro/tools")
    from live_midi import ports, open_out, Clock, play_pattern

    out = open_out("Bus 2")                  # substring match: "IAC Driver Bus 2", "IAC Driver (Bus 2)"
    out.note(60, vel=100, dur=0.25)          # returns at once, note-off is scheduled (seconds)
    clock = Clock("Bus 1")                   # Live: Preferences > Link/Tempo/MIDI > Output: Bus 1, Sync on
    clock.next_beat(4.0)                     # blocks until the next bar line (4/4)
    p = play_pattern(out, clock, notes, loop_beats=4.0)   # notes as for add_notes_to_clip
    p.stop()

Channels are 0-15 (0 = Live's "Ch. 1"). Beats are quarter notes, counted from Live's song
start: Live sends Song Position Pointer + Continue when it starts mid-song, which `Clock`
honours. Needs `pip install "ableton-mcp-pro[midi]"` (mido + python-rtmidi).

    python tools/live_midi.py ports
    python tools/live_midi.py clock "Bus 1"        # prints bpm / beat while Live sends clock
    python tools/live_midi.py note "Bus 2" 60 [--vel 100 --dur 0.25 --ch 0]
    python tools/live_midi.py panic "Bus 2"
"""

from __future__ import annotations

import heapq
import itertools
import math
import re
import threading
import time
from collections import deque

PPQN = 24  # MIDI clock ticks per quarter note

_mido_mod = None


def _mido():
    """Import mido lazily, on the rtmidi backend."""
    global _mido_mod
    if _mido_mod is None:
        try:
            import mido
            import rtmidi  # noqa: F401  (python-rtmidi; mido's default backend needs it)
        except ImportError as e:
            raise ImportError(
                "live_midi needs mido and python-rtmidi: "
                "pip install \"ableton-mcp-pro[midi]\"  (or: uv pip install mido python-rtmidi)"
            ) from e
        mido.set_backend("mido.backends.rtmidi")
        _mido_mod = mido
    return _mido_mod


def _sleep_until(t: float, spin: float = 0.0015):
    """Sleep to monotonic `t`, typically within 0.05 ms. macOS oversleeps (~2 ms on short
    sleeps, 2-5% on long ones), so sleep short of it in shrinking steps and spin (yielding)
    for the last `spin` seconds."""
    while True:
        d = t - time.monotonic()
        if d <= spin:
            break
        time.sleep((d - spin) * 0.7 + 0.0002)
    while time.monotonic() < t:
        time.sleep(0)


def _msg(type_, **kw):
    return _mido().Message(type_, **kw)


# ---------------------------------------------------------------- ports

def ports() -> dict:
    """{"inputs": [...], "outputs": [...]} as CoreMIDI names them ("IAC Driver Bus 1", ...)."""
    m = _mido()
    return {"inputs": m.get_input_names(), "outputs": m.get_output_names()}


def _norm(s: str) -> str:
    # Live shows "IAC Driver (Bus 2)", CoreMIDI/mido say "IAC Driver Bus 2"
    return re.sub(r"\s+", " ", re.sub(r"[()]", " ", s)).strip().lower()


def find_port(needle: str, names: list[str], kind: str = "port") -> str:
    """Pick the one name matching `needle`: exact, else whole-word substring ("Bus 1" does not
    match "Bus 10"), else plain substring; case- and parenthesis-insensitive."""
    if needle in names:
        return needle
    n = _norm(needle)
    word = [p for p in names if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", _norm(p))]
    sub = [p for p in names if n in _norm(p)]
    for cands in (word, sub):
        if len(cands) == 1:
            return cands[0]
        if len(cands) > 1:
            raise ValueError(f"MIDI {kind} {needle!r} is ambiguous: {cands}")
    avail = ", ".join(names) or "none (enable the IAC Driver in Audio MIDI Setup > MIDI Studio)"
    raise ValueError(f"no MIDI {kind} matching {needle!r}; available: {avail}")


def open_out(name: str, virtual: bool = False) -> "Out":
    """Open an output by substring. `virtual=True` creates a CoreMIDI source called `name`."""
    m = _mido()
    if virtual:
        return Out(m.open_output(name, virtual=True))
    return Out(m.open_output(find_port(name, m.get_output_names(), "output")))


def open_in(name: str, callback=None, virtual: bool = False):
    """Open a mido input by substring; `callback(msg)` runs on rtmidi's thread."""
    m = _mido()
    if virtual:
        return m.open_input(name, virtual=True, callback=callback)
    return m.open_input(find_port(name, m.get_input_names(), "input"), callback=callback)


# ---------------------------------------------------------------- output

class _Scheduler:
    """One background thread sending messages at monotonic times."""

    def __init__(self, send):
        self._send = send
        self._q: list = []
        self._seq = itertools.count()
        self._cv = threading.Condition()
        self._closed = False
        self._t = threading.Thread(target=self._run, name="live_midi-scheduler", daemon=True)
        self._t.start()

    def at(self, when: float, msg, key=None) -> list:
        """Send `msg` at monotonic `when`. Returns a handle; `cancel(handle)` drops it."""
        item = [when, next(self._seq), msg, key, True]
        with self._cv:
            heapq.heappush(self._q, item)
            self._cv.notify()
        return item

    def cancel(self, item) -> bool:
        with self._cv:
            was, item[4] = item[4], False
            return was

    def drain(self) -> list:
        """Remove and return every pending message (the caller decides what to do with them)."""
        with self._cv:
            out = [it[2] for it in sorted(self._q) if it[4]]
            for it in self._q:
                it[4] = False
            self._q.clear()
            return out

    def _run(self):
        with self._cv:
            while not self._closed:
                if not self._q:
                    self._cv.wait()
                    continue
                when = self._q[0][0]
                dt = when - time.monotonic()
                if dt > 0.008:                  # wake well short of it (see _sleep_until)
                    self._cv.wait((dt - 0.004) * 0.8)
                    continue
                if dt > 0:
                    self._cv.release()
                    try:
                        _sleep_until(when)
                    finally:
                        self._cv.acquire()
                    continue
                item = heapq.heappop(self._q)
                if item[4]:
                    item[4] = False
                    self._cv.release()          # never send under our lock (Out takes its own)
                    try:
                        self._send(item[2], item[3], item)
                    finally:
                        self._cv.acquire()

    def close(self):
        with self._cv:
            self._closed = True
            self._cv.notify()


class Out:
    """A mido output with non-blocking notes. Thread-safe."""

    def __init__(self, port):
        self.port = port
        self.name = port.name
        self._lock = threading.Lock()
        self._held: dict = {}          # (ch, pitch) -> scheduled note-off handle, or None
        self._sched = _Scheduler(self._sched_send)

    def send(self, msg):
        with self._lock:
            self.port.send(msg)

    def _sched_send(self, msg, key, item):
        with self._lock:
            if key is not None:
                if self._held.get(key) is not item:
                    return                 # the note was retriggered or released meanwhile
                del self._held[key]
            self.port.send(msg)

    def note_on(self, pitch: int, vel: int = 100, ch: int = 0):
        with self._lock:
            self._held.setdefault((ch, pitch), None)
            self.port.send(_msg("note_on", note=pitch, velocity=vel, channel=ch))

    def note_off(self, pitch: int, ch: int = 0, vel: int = 0):
        with self._lock:
            h = self._held.pop((ch, pitch), None)
            if h is not None:
                self._sched.cancel(h)
            self.port.send(_msg("note_off", note=pitch, velocity=vel, channel=ch))

    def note(self, pitch: int, vel: int = 100, dur: float = 0.25, ch: int = 0, at: float | None = None):
        """Play a note for `dur` seconds without blocking. Retriggering a sounding pitch ends the
        old note first. `at` (time.monotonic()) schedules the note-on too."""
        if at is not None and at > time.monotonic():
            self._sched.at(at, _msg("note_on", note=pitch, velocity=vel, channel=ch))
            self._sched.at(at + dur, _msg("note_off", note=pitch, velocity=0, channel=ch))
            return
        key = (ch, pitch)
        with self._lock:
            if key in self._held:          # retrigger: end the sounding note first
                old = self._held.pop(key)
                if old is not None:
                    self._sched.cancel(old)
                self.port.send(_msg("note_off", note=pitch, velocity=0, channel=ch))
            self.port.send(_msg("note_on", note=pitch, velocity=vel, channel=ch))
            self._held[key] = self._sched.at(time.monotonic() + dur,
                                             _msg("note_off", note=pitch, velocity=0, channel=ch), key)

    def cc(self, num: int, val: int, ch: int = 0):
        self.send(_msg("control_change", control=num, value=val, channel=ch))

    def program(self, n: int, ch: int = 0):
        self.send(_msg("program_change", program=n, channel=ch))

    def panic(self):
        """Note-off for everything this Out holds or has scheduled, then All Notes Off (CC 123)
        and All Sound Off (CC 120) on all 16 channels."""
        self.release()
        with self._lock:
            for ch in range(16):
                self.port.send(_msg("control_change", control=123, value=0, channel=ch))
                self.port.send(_msg("control_change", control=120, value=0, channel=ch))

    def release(self):
        """Note-off for every note this Out holds or has scheduled (no CCs)."""
        pending = self._sched.drain()
        with self._lock:
            for msg in pending:
                if msg.type == "note_off":
                    self.port.send(msg)
            for (ch, pitch) in list(self._held):
                self.port.send(_msg("note_off", note=pitch, velocity=0, channel=ch))
            self._held.clear()

    def close(self):
        self.release()
        self._sched.close()
        self.port.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ---------------------------------------------------------------- clock

class Clock:
    """Follows MIDI clock (0xF8, 24 ppqn), Start/Stop/Continue and Song Position Pointer.

    Clock("Bus 1") listens on a port; Clock() doesn't, and `feed(msg, t)` drives it (tests,
    or your own input callback). Thread-safe; `beat` is interpolated between ticks.

    Position rules (MIDI spec): Start -> the next tick is beat 0; SPP (sixteenths) sets the
    position the next tick plays after Continue; Stop freezes it; ticks move the position only
    while playing. `bpm` comes from ticks whether or not the transport runs.
    """

    def __init__(self, port: str | None = None, window: int = 48, virtual: bool = False):
        self._cv = threading.Condition()
        self._times: deque = deque(maxlen=window + 1)   # recent tick times, for bpm
        self._next = 0          # tick index the next clock plays
        self._tick = None       # index of the last tick played (None: none since start/continue)
        self._last_t = None     # time of that tick
        self.playing = False
        self.port = None
        if port is not None:
            self.port = open_in(port, callback=self.feed, virtual=virtual)

    # -- input
    def feed(self, msg, t: float | None = None):
        """Handle one mido message received at monotonic time `t` (default: now)."""
        if t is None:
            t = time.monotonic()
        typ = msg.type
        with self._cv:
            if typ == "clock":
                if self._times and t - self._times[-1] > 0.25:   # < 10 bpm: a gap, not a tempo
                    self._times.clear()
                self._times.append(t)
                if self.playing:
                    self._tick = self._next
                    self._next += 1
                    self._last_t = t
            elif typ == "start":
                self._next, self._tick, self.playing = 0, None, True
            elif typ == "continue":
                self._tick, self.playing = None, True
            elif typ == "stop":
                self._tick, self.playing = None, False
            elif typ == "songpos":
                self._next, self._tick = msg.pos * 6, None       # pos is in sixteenths
            else:
                return
            self._cv.notify_all()

    # -- readings
    def _bpm(self):
        ts = self._times
        if len(ts) < 3:
            return None
        span = ts[-1] - ts[0]
        return 60.0 * (len(ts) - 1) / (span * PPQN) if span > 0 else None

    @property
    def bpm(self) -> float | None:
        """Tempo averaged over the last `window` ticks (2 beats by default); None before 3 ticks."""
        with self._cv:
            return self._bpm()

    def _beat(self, now=None):
        if self._tick is None or not self.playing:
            return self._next / PPQN
        bpm = self._bpm()
        frac = 0.0
        if bpm:
            tick_dt = 60.0 / (bpm * PPQN)
            now = time.monotonic() if now is None else now
            frac = min(max(now - self._last_t, 0.0) / tick_dt, 1.0)   # never run past the next tick
        return (self._tick + frac) / PPQN

    @property
    def beat(self) -> float:
        """Beats (quarter notes) since song start, interpolated between ticks while playing."""
        with self._cv:
            return self._beat()

    def beat_at(self, now: float) -> float:
        """`beat` as of monotonic time `now` (for tests and synthetic feeds)."""
        with self._cv:
            return self._beat(now)

    def _time_of(self, beat):
        # Anchor on the window's best-fit time for the last tick (mean of the window plus half
        # its span), not the raw last tick, so one late tick doesn't shift the prediction.
        bpm = self._bpm()
        if not (self.playing and bpm and self._tick is not None):
            return None
        ts = self._times
        period = (ts[-1] - ts[0]) / (len(ts) - 1)
        anchor = sum(ts) / len(ts) + period * (len(ts) - 1) / 2
        return anchor + (beat * PPQN - self._tick) * period

    def time_of(self, beat: float) -> float | None:
        """Predicted monotonic time of `beat` at the current tempo (None if not running)."""
        with self._cv:
            return self._time_of(beat)

    def wait_playing(self, timeout: float | None = None, cancel: threading.Event | None = None) -> bool:
        """Block until the transport runs and the first tick has arrived."""
        end = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while not (self.playing and self._tick is not None):
                if cancel is not None and cancel.is_set():
                    return False
                left = None if end is None else end - time.monotonic()
                if left is not None and left <= 0:
                    return False
                self._cv.wait(0.05 if left is None else min(left, 0.05))
            return True

    def wait_until(self, beat: float, timeout: float | None = None,
                   cancel: threading.Event | None = None, while_playing: bool = False) -> bool:
        """Block until the clock reaches `beat`. Waits on ticks while far away and sleeps to the
        predicted time for the last stretch, so it returns between ticks, not on the next one.
        False on timeout, on `cancel` being set, or (with `while_playing`) on transport stop."""
        end = None if timeout is None else time.monotonic() + timeout
        with self._cv:
            while True:
                if cancel is not None and cancel.is_set():
                    return False
                if while_playing and not self.playing:
                    return False
                now = time.monotonic()
                if self._beat(now) >= beat - 1e-9:
                    return True
                left = None if end is None else end - now
                if left is not None and left <= 0:
                    return False
                when = self._time_of(beat)
                if when is not None:
                    dt = when - now
                    if dt <= 0:
                        return True
                    if dt <= 0.03:                  # last stretch: sleep to it, unlocked
                        if left is not None and dt > left:
                            self._cv.wait(left)
                            return False
                        self._cv.release()
                        try:
                            _sleep_until(when)
                        finally:
                            self._cv.acquire()
                        return not (cancel is not None and cancel.is_set())
                    wait = min(dt - 0.02, 0.1)      # woken early by every tick anyway
                else:
                    wait = 0.05
                self._cv.wait(wait if left is None else min(wait, left))

    def next_boundary(self, division: float = 1.0) -> float:
        """The next multiple of `division` beats strictly after now (4.0 = next bar in 4/4)."""
        b = self.beat
        return (math.floor(b / division + 1e-6) + 1) * division

    def next_beat(self, division: float = 1.0, **kw) -> float:
        """Block until the next multiple of `division` beats; return that beat."""
        target = self.next_boundary(division)
        self.wait_until(target, **kw)
        return target

    def close(self):
        if self.port is not None:
            self.port.close()


# ---------------------------------------------------------------- patterns

class Pattern:
    """A running `play_pattern`; `stop()` ends it and releases its notes."""

    def __init__(self):
        self.cancel = threading.Event()
        self.start_beat: float | None = None
        self.thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def stop(self, wait: bool = True):
        self.cancel.set()
        if wait and self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(2.0)

    def join(self, timeout=None):
        if self.thread is not None:
            self.thread.join(timeout)


def play_pattern(out: Out, clock: Clock, notes: list[dict], loop_beats: float,
                 quantize_to: float = 4.0, ch: int = 0, loops: int | None = None,
                 stop_with_transport: bool = True) -> Pattern:
    """Loop `notes` ([{pitch, start_time, duration, velocity, mute?}] in beats, the
    add_notes_to_clip schema) every `loop_beats`, starting on the next `quantize_to` boundary of
    `clock`, in a background thread. Waits for the transport if it isn't running. `loops=None`
    repeats until `stop()`; with `stop_with_transport` it also ends when Live stops."""
    events = []   # (beat offset, order, kind, pitch, vel); offs sort before ons at equal times
    for n in notes:
        if n.get("mute"):
            continue
        s, d = float(n["start_time"]), float(n.get("duration", 0.25))
        p, v = int(n["pitch"]), int(n.get("velocity", 100))
        events.append((s, 1, "on", p, v))
        events.append((s + max(d, 1e-3), 0, "off", p, 0))
    events.sort()
    pat = Pattern()

    def run():
        sounding: dict = {}
        try:
            if not clock.wait_playing(cancel=pat.cancel):
                return
            start = clock.next_boundary(quantize_to)
            pat.start_beat = start
            heap = [(start + e[0], i, 0, e) for i, e in enumerate(events)]
            heapq.heapify(heap)
            while heap:
                at, i, k, (off, order, kind, pitch, vel) = heapq.heappop(heap)
                if not clock.wait_until(at, cancel=pat.cancel, while_playing=stop_with_transport):
                    return
                if kind == "on":
                    if sounding.get(pitch):
                        out.send(_msg("note_off", note=pitch, velocity=0, channel=ch))
                    out.send(_msg("note_on", note=pitch, velocity=vel, channel=ch))
                    sounding[pitch] = sounding.get(pitch, 0) + 1
                else:
                    if sounding.get(pitch):
                        sounding[pitch] -= 1
                        if not sounding[pitch]:
                            out.send(_msg("note_off", note=pitch, velocity=0, channel=ch))
                if kind == "on" or order == 0:     # queue this event's next repetition
                    if loops is None or k + 1 < loops:
                        heapq.heappush(heap, (at + loop_beats, i, k + 1, (off, order, kind, pitch, vel)))
        finally:
            for pitch, c in sounding.items():
                if c:
                    out.send(_msg("note_off", note=pitch, velocity=0, channel=ch))

    pat.thread = threading.Thread(target=run, name="live_midi-pattern", daemon=True)
    pat.thread.start()
    return pat


# ---------------------------------------------------------------- CLI

def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="MIDI fast path to Ableton Live (IAC buses)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="list MIDI inputs and outputs")
    c = sub.add_parser("clock", help="print bpm / beat from a port Live sends clock to")
    c.add_argument("port")
    n = sub.add_parser("note", help="send one note")
    n.add_argument("port")
    n.add_argument("pitch", type=int)
    n.add_argument("--vel", type=int, default=100)
    n.add_argument("--dur", type=float, default=0.25, help="seconds")
    n.add_argument("--ch", type=int, default=0, help="0-15 (0 = Live's Ch. 1)")
    p = sub.add_parser("panic", help="all notes off on all channels")
    p.add_argument("port")
    a = ap.parse_args(argv)

    if a.cmd == "ports":
        ps = ports()
        print("inputs:\n  " + ("\n  ".join(ps["inputs"]) or "(none)"))
        print("outputs:\n  " + ("\n  ".join(ps["outputs"]) or "(none)"))
    elif a.cmd == "clock":
        clock = Clock(a.port)
        print(f"listening on {clock.port.name} (Ctrl-C to quit)")
        try:
            while True:
                bpm, b = clock.bpm, clock.beat
                bar, beat = divmod(b, 4.0)
                state = "playing" if clock.playing else "stopped"
                tempo = f"{bpm:7.2f}" if bpm else "     --"
                print(f"\r{state}  bpm {tempo}  beat {b:9.3f}  ({int(bar) + 1}.{int(beat) + 1})   ",
                      end="", flush=True)
                time.sleep(0.1)
        except KeyboardInterrupt:
            print()
        finally:
            clock.close()
    elif a.cmd == "note":
        with open_out(a.port) as out:
            out.note(a.pitch, vel=a.vel, dur=a.dur, ch=a.ch)
            time.sleep(a.dur + 0.02)
            print(f"sent {a.pitch} vel {a.vel} ch {a.ch} for {a.dur}s to {out.name}")
    elif a.cmd == "panic":
        with open_out(a.port) as out:
            out.panic()
            print(f"panic sent to {out.name}")


if __name__ == "__main__":
    import sys
    try:
        _main()
    except (ValueError, ImportError) as e:
        sys.exit(f"error: {e}")
