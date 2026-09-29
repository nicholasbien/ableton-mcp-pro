"""
Integration test for the Remote Script's `batch` and `get_events` commands, against a running
Live with the AbletonMCP control surface:

    python tools/test_batch_events.py

Works on scratch tracks it adds at the end of the set and deletes afterwards; restores tempo and
stops playback. Prints timings for single calls vs one batch.
"""

from __future__ import annotations

import threading
import time

from live_client import LiveError, batch, events, live, ref


def timed(fn):
    t = time.perf_counter()
    r = fn()
    return r, time.perf_counter() - t


def test_speed():
    n = int(live("get_session_info")["track_count"])
    k = max(1, min(n, 10))
    _, singles = timed(lambda: [live("get_track_info", {"track_index": i % n}) for i in range(10)])
    _, one = timed(lambda: batch([("get_track_info", {"track_index": i % n}) for i in range(10)]))
    _, sets_single = timed(lambda: [live("set_metronome", {"on": False}) for _ in range(10)])
    _, sets_batch = timed(lambda: batch([("set_metronome", {"on": False})] * 10))
    print(f"10 reads:  {singles:.2f} s one by one, {one:.2f} s batched")
    print(f"10 writes: {sets_single:.2f} s one by one, {sets_batch:.2f} s batched")
    assert k


def test_refs_and_cleanup():
    before = int(live("get_session_info")["track_count"])
    notes = [{"pitch": 36 + i, "start_time": i * 0.5, "duration": 0.25, "velocity": 100} for i in range(8)]
    res, dt = timed(lambda: batch([
        ("create_midi_track", {"index": -1}),
        ("set_track_name", {"track_index": ref(0, "index"), "name": "batch test"}),
        ("create_clip", {"track_index": ref(0, "index"), "clip_index": 0, "length": 4.0}),
        ("add_notes_to_clip", {"track_index": ref(0, "index"), "clip_index": 0, "notes": notes}),
        ("set_clip_name", {"track_index": ref(0, "index"), "clip_index": 0, "name": "riff"}),
        ("set_track_volume", {"track_index": ref(0, "index"), "volume": 0.5}),
        ("get_clip_notes", {"track_index": ref(0, "index"), "clip_index": 0}),
    ]))
    idx = res[0]["index"]
    print(f"build a track + clip + 8 notes in one batch: {dt:.2f} s")
    try:
        assert idx == before, (idx, before)
        info = live("get_track_info", {"track_index": idx})
        assert info["name"] == "batch test", info["name"]
        assert len(res[6]["notes"]) == 8, res[6]
    finally:
        live("delete_track", {"track_index": idx})
    assert int(live("get_session_info")["track_count"]) == before


def test_errors():
    n = int(live("get_session_info")["track_count"])
    cmds = [("get_track_info", {"track_index": 0}),
            ("get_track_info", {"track_index": n + 50}),     # fails
            ("get_session_info", {})]
    try:
        batch(cmds)
        raise AssertionError("expected LiveError")
    except LiveError as e:
        assert "batch command 1" in str(e), e
    r = live("batch", {"commands": [{"type": c, "params": p} for c, p in cmds]})
    assert r["completed"] == 2 and not r["ok"], r
    r = batch(cmds, stop_on_error=False)
    assert [x["status"] for x in r] == ["success", "error", "success"], r
    for bad in ("record_arrangement", "get_events", "batch", "nope"):
        try:
            batch([(bad, {})])
            raise AssertionError(bad + " should be refused")
        except LiveError as e:
            assert "can't be batched" in str(e), e
    try:
        batch([("set_track_name", {"track_index": ref(3, "index"), "name": "x"})])
        raise AssertionError("dangling $ref should fail")
    except LiveError as e:
        assert "hasn't run" in str(e), e


def test_events():
    got: list[dict] = []
    stop = threading.Event()

    def collect():
        for ev in events(wait=2.0):
            got.append(ev)
            if stop.is_set():
                return

    th = threading.Thread(target=collect, daemon=True)
    th.start()
    time.sleep(1.0)  # let events() take its starting point

    tempo = live("get_session_info")["tempo"]
    res = batch([("create_midi_track", {"index": -1}),
                 ("set_track_name", {"track_index": ref(0, "index"), "name": "events test"}),
                 ("create_clip", {"track_index": ref(0, "index"), "clip_index": 0, "length": 4.0})])
    idx = res[0]["index"]
    try:
        # no sleep: the new track must already be watched when create returns
        live("set_tempo", {"tempo": tempo + 7})
        live("set_track_mute", {"track_index": idx, "mute": True})
        live("fire_clip", {"track_index": idx, "clip_index": 0})
        time.sleep(1.5)
        live("stop_playback")
        time.sleep(1.0)
    finally:
        batch([("stop_all_clips", {}), ("set_tempo", {"tempo": tempo}),
               ("delete_track", {"track_index": idx})], stop_on_error=False)
    time.sleep(2.0)
    stop.set()
    th.join(timeout=5)

    types = [e["type"] for e in got]
    print("events:", ", ".join(types))
    for want in ("tracks_changed", "tempo", "track_mute", "clip_playing", "is_playing"):
        assert want in types, (want, types)
    mute = next(e for e in got if e["type"] == "track_mute")
    assert mute["track"] == "events test" and mute["value"] is True, mute
    playing = [e for e in got if e["type"] == "clip_playing" and e["track"] == "events test"]
    assert any(e["clip_index"] == 0 for e in playing), playing
    seqs = [e["seq"] for e in got]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), seqs


if __name__ == "__main__":
    for t in (test_speed, test_refs_and_cleanup, test_errors, test_events):
        t()
        print("ok", t.__name__)
