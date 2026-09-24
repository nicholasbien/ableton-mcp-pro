"""
Tests for live_midi.py; plain asserts, no Live needed:

    python tools/test_live_midi.py

Synthetic: the Clock fed by hand (bpm, SPP, start/stop/continue, wait_until, next_beat),
Out's scheduler and play_pattern against a fake port, port-name matching. Loopback, when the
ports exist: an IAC bus (LIVE_MIDI_TEST_BUS, default the highest-numbered one; it sends a few
notes and a burst of clock on it, so pick a bus nothing is listening to) and an rtmidi virtual
port, each measuring note latency and following clock sent through it.
"""

import os
import statistics
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import live_midi as lm
from live_midi import Clock, Out, find_port, play_pattern

mido = lm._mido()
M = mido.Message
TICK_120 = 60.0 / (120 * 24)


def close(a, b, tol):
    return abs(a - b) <= tol


def feed_ticks(clock, n, bpm, t0):
    dt = 60.0 / (bpm * 24)
    for i in range(n):
        clock.feed(M("clock"), t0 + i * dt)
    return t0 + (n - 1) * dt


class FakePort:
    name = "fake"

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append((time.monotonic(), msg))

    def close(self):
        pass


def realtime_ticks(clock, bpm, stop, first=None):
    """Feed Start + ticks at `bpm` in real time until `stop` is set (a stand-in for Live).
    The ideal time of tick 0 (beat 0) goes in `first`."""
    dt = 60.0 / (bpm * 24)
    clock.feed(M("start"))
    t = time.monotonic() + dt
    if first is not None:
        first.append(t)
    while not stop.is_set():
        lm._sleep_until(t)
        clock.feed(M("clock"))
        t += dt


# ---------------------------------------------------------------- synthetic

def test_bpm():
    c = Clock()
    assert c.bpm is None
    t = feed_ticks(c, 49, 120.0, 100.0)
    assert close(c.bpm, 120.0, 1e-6), c.bpm
    feed_ticks(c, 49, 140.0, t + 60.0 / (140 * 24))      # the window slides over to the new tempo
    assert close(c.bpm, 140.0, 1e-6), c.bpm
    # jittered ticks (+-1 ms, like a busy IAC bus) still average out
    c = Clock()
    import random
    random.seed(1)
    for i in range(96):
        c.feed(M("clock"), 200.0 + i * TICK_120 + random.uniform(-0.001, 0.001))
    assert close(c.bpm, 120.0, 0.5), c.bpm
    # a gap (transport idle, no clock) resets the estimate instead of averaging it in
    c.feed(M("clock"), 300.0)
    assert c.bpm is None


def test_start_stop_position():
    c = Clock()
    feed_ticks(c, 10, 120, 0.0)                     # clock while stopped: tempo only
    assert not c.playing and c.beat == 0.0
    c.feed(M("start"), 1.0)
    assert c.playing and c.beat == 0.0
    t = feed_ticks(c, 25, 120, 1.0)                  # ticks 0..24 -> beat 1
    assert close(c.beat_at(t), 1.0, 1e-9), c.beat_at(t)
    assert close(c.beat_at(t + TICK_120 / 2), 1.0 + 0.5 / 24, 1e-9)   # interpolated
    assert close(c.beat_at(t + 10), 1.0 + 1 / 24, 1e-9)               # capped at one tick
    c.feed(M("stop"), t + 0.001)
    assert not c.playing
    frozen = c.beat
    feed_ticks(c, 30, 120, t + 0.01)
    assert c.beat == frozen, (c.beat, frozen)         # stopped: ticks don't move the position
    c.feed(M("continue"), t + 1)
    t2 = feed_ticks(c, 1, 120, t + 1.01)
    assert close(c.beat_at(t2), 25 / 24, 1e-9), c.beat_at(t2)   # resumes on the next tick
    c.feed(M("start"), t2 + 1)                                    # Start rewinds to 0
    t3 = feed_ticks(c, 1, 120, t2 + 1.01)
    assert c.beat_at(t3) == 0.0


def test_spp():
    c = Clock()
    feed_ticks(c, 5, 120, 0.0)
    c.feed(M("songpos", pos=64), 1.0)                # 64 sixteenths = bar 5 = beat 16
    assert c.beat == 16.0 and not c.playing
    c.feed(M("continue"), 1.01)
    assert c.beat == 16.0
    t = feed_ticks(c, 13, 120, 1.02)                 # first tick plays beat 16, +12 ticks = 16.5
    assert close(c.beat_at(t), 16.5, 1e-9), c.beat_at(t)
    c.feed(M("stop"), t + 0.01)
    c.feed(M("songpos", pos=2), t + 0.02)            # relocate while stopped: beat 0.5
    assert c.beat == 0.5
    c.feed(M("note_on", note=60), t + 0.03)          # ignored
    assert c.beat == 0.5


def test_time_of():
    c = Clock()
    c.feed(M("start"), 10.0)
    t = feed_ticks(c, 49, 120, 10.0)                 # tick 48 = beat 2 at t
    assert close(c.time_of(2.0), t, 1e-9)
    assert close(c.time_of(4.0), t + 1.0, 1e-9)       # 2 beats at 120 bpm = 1 s


def test_wait_until_realtime():
    c = Clock()
    stop = threading.Event()
    first = []
    th = threading.Thread(target=realtime_ticks, args=(c, 120, stop, first), daemon=True)
    th.start()
    try:
        assert c.wait_playing(timeout=1.0)
        # land between ticks: 1 + 1/48 beat is half a tick after beat 1
        target = 1.0 + 0.5 / 24
        assert c.wait_until(target, timeout=3.0)
        err = time.monotonic() - (first[0] + target * 0.5)
        assert -0.002 < err < 0.005, f"wait_until off by {err * 1000:.1f} ms"
        b = c.next_beat(1.0, timeout=3.0)
        assert b == 2.0, b
        assert close(c.beat, 2.0, 0.02), c.beat
        # timeout and cancel
        t0 = time.monotonic()
        assert not c.wait_until(1000.0, timeout=0.2)
        assert close(time.monotonic() - t0, 0.2, 0.05)
        ev = threading.Event()
        threading.Timer(0.1, ev.set).start()
        assert not c.wait_until(1000.0, cancel=ev)
        assert c.next_boundary(4.0) == 4.0
    finally:
        stop.set()
        th.join()
    c.feed(M("stop"))
    assert not c.wait_until(1000.0, while_playing=True)
    print(f"  wait_until lands {err * 1000:+.2f} ms from the ideal time")


def test_out_scheduler():
    port = FakePort()
    out = Out(port)
    t0 = time.monotonic()
    out.note(60, vel=90, dur=0.1)
    assert time.monotonic() - t0 < 0.005, "note() blocked"
    assert [m.type for _, m in port.sent] == ["note_on"]
    time.sleep(0.15)
    (t_on, on), (t_off, off) = port.sent
    assert off.type == "note_off" and off.note == 60
    assert close(t_off - t_on, 0.1, 0.005), t_off - t_on
    # retrigger: old note ends first, then only the new note's off follows (no early cut)
    port.sent.clear()
    out.note(62, dur=0.1)
    time.sleep(0.05)
    out.note(62, dur=0.1)
    time.sleep(0.2)
    types = [m.type for _, m in port.sent]
    assert types == ["note_on", "note_off", "note_on", "note_off"], types
    assert close(port.sent[3][0] - port.sent[2][0], 0.1, 0.005)
    # cc / program / note_on-off
    port.sent.clear()
    out.cc(74, 64, ch=2)
    out.program(5)
    out.note_on(64)
    out.note_off(64)
    got = [(m.type, getattr(m, "channel", None)) for _, m in port.sent]
    assert got == [("control_change", 2), ("program_change", 0), ("note_on", 0), ("note_off", 0)], got
    # panic: releases held + scheduled notes, then CC 123/120 on 16 channels
    port.sent.clear()
    out.note_on(40)
    out.note(41, dur=5.0)
    out.panic()
    offs = sorted(m.note for _, m in port.sent if m.type == "note_off")
    ccs = [m for _, m in port.sent if m.type == "control_change"]
    assert 40 in offs and 41 in offs, offs
    assert len(ccs) == 32 and {m.channel for m in ccs} == set(range(16))
    out.close()


def test_play_pattern():
    c = Clock()
    port = FakePort()
    out = Out(port)
    notes = [{"pitch": 36, "start_time": 0.0, "duration": 0.25, "velocity": 110},
             {"pitch": 42, "start_time": 0.5, "duration": 0.25, "velocity": 80},
             {"pitch": 99, "start_time": 0.75, "duration": 0.1, "velocity": 80, "mute": True}]
    stop = threading.Event()
    first = []
    th = threading.Thread(target=realtime_ticks, args=(c, 240, stop, first), daemon=True)  # 0.25 s/beat
    pat = play_pattern(out, c, notes, loop_beats=1.0, quantize_to=1.0)
    th.start()
    try:
        time.sleep(1.05)                    # beats 1, 2, 3 play (quantized start at beat 1)
        pat.stop()
        assert not pat.running
    finally:
        stop.set()
        th.join()
    assert pat.start_beat == 1.0, pat.start_beat
    ons = [(t - first[0], m.note) for t, m in port.sent if m.type == "note_on"]
    assert [n for _, n in ons][:6] == [36, 42, 36, 42, 36, 42], ons
    assert 99 not in [n for _, n in ons]
    # onsets against the ideal grid (beat b at b * 0.25 s)
    errs = [t - (1.0 + i // 2 + (i % 2) * 0.5) * 0.25 for i, (t, _) in enumerate(ons[:6])]
    assert max(abs(e) for e in errs) < 0.005, errs
    # everything released after stop
    held = {}
    for _, m in port.sent:
        if m.type == "note_on":
            held[m.note] = held.get(m.note, 0) + 1
        elif m.type == "note_off":
            held[m.note] = held.get(m.note, 0) - 1
    assert all(v <= 0 for v in held.values()), held
    # stops with the transport
    pat = play_pattern(out, c, notes, loop_beats=1.0)
    stop.clear()
    th = threading.Thread(target=realtime_ticks, args=(c, 240, stop), daemon=True)
    th.start()
    time.sleep(0.1)
    stop.set()
    th.join()
    c.feed(M("stop"))
    pat.join(1.0)
    assert not pat.running
    out.close()
    print(f"  play_pattern onsets within {max(abs(e) for e in errs) * 1000:.2f} ms of the grid")


def test_find_port():
    names = ["IAC Driver Bus 1", "IAC Driver Bus 10", "IAC Driver Bus 2", "Keystation 49"]
    assert find_port("Bus 1", names) == "IAC Driver Bus 1"          # whole word, not Bus 10
    assert find_port("IAC Driver (Bus 2)", names) == "IAC Driver Bus 2"   # Live's spelling
    assert find_port("keystation", names) == "Keystation 49"
    assert find_port("IAC Driver Bus 10", names) == "IAC Driver Bus 10"
    for bad, word in (("IAC", "ambiguous"), ("Bus 7", "available")):
        try:
            find_port(bad, names)
        except ValueError as e:
            assert word in str(e), e
        else:
            raise AssertionError(f"{bad!r} should not match")


# ---------------------------------------------------------------- loopback

def loopback(out, in_name, label):
    """Send notes and clock through `out`, receive on `in_name`; report latency."""
    got = []
    sent_t = {}
    clock = Clock()

    def cb(msg):
        t = time.monotonic()
        if msg.type == "note_on":
            got.append((msg.note, t))
        else:
            clock.feed(msg, t)

    inp = lm.open_in(in_name, callback=cb)
    time.sleep(0.1)
    try:
        for i in range(50):
            sent_t[i] = time.monotonic()
            out.send(M("note_on", note=i + 20, velocity=1, channel=15))
            out.send(M("note_off", note=i + 20, velocity=0, channel=15))
            time.sleep(0.005)
        time.sleep(0.1)
        assert len(got) == 50, f"{label}: received {len(got)}/50 notes"
        lat = [t - sent_t[n - 20] for n, t in got]
        # 2 beats of clock at 120 bpm through the port
        out.send(M("start"))
        t = time.monotonic()
        for _ in range(49):
            t += TICK_120
            lm._sleep_until(t)
            out.send(M("clock"))
        time.sleep(0.05)
        out.send(M("stop"))
        time.sleep(0.05)
        assert clock.bpm is not None and close(clock.bpm, 120.0, 1.0), f"{label}: bpm {clock.bpm}"
        assert close(clock.beat, 2.0, 1 / 24 + 1e-9), f"{label}: beat {clock.beat}"
    finally:
        inp.close()
    ms = [x * 1000 for x in lat]
    print(f"  {label}: note latency median {statistics.median(ms):.3f} ms, "
          f"max {max(ms):.3f} ms (n=50); clock through it: {clock.bpm:.2f} bpm")


def test_iac_loopback():
    outs = [n for n in mido.get_output_names() if "IAC" in n]
    ins = set(mido.get_input_names())
    bus = os.environ.get("LIVE_MIDI_TEST_BUS")
    if not bus:
        both = [n for n in outs if n in ins]
        if not both:
            print("  SKIP: no IAC bus (enable the IAC Driver in Audio MIDI Setup)")
            return
        bus = sorted(both, key=lambda n: [int(x) if x.isdigit() else x for x in n.split()])[-1]
    out = lm.open_out(bus)
    try:
        loopback(out, bus, out.name)
    finally:
        out.close()


def test_virtual_loopback():
    name = f"live_midi test {os.getpid()}"
    try:
        out = lm.open_out(name, virtual=True)
    except Exception as e:  # virtual ports need CoreMIDI/ALSA; not on Windows
        print(f"  SKIP: no virtual ports ({e})")
        return
    try:
        for _ in range(20):
            if any(name in n for n in mido.get_input_names()):
                break
            time.sleep(0.05)
        loopback(out, name, "virtual port")
    finally:
        out.close()


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        print(fn.__name__)
        fn()
    print(f"ok ({len(tests)} tests)")
