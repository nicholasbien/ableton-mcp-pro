"""
Minimal Python client for the AbletonMCP remote script (Live, port 9877), for scripts that
want to drive Live without going through the MCP server:

    import sys; sys.path.insert(0, "path/to/ableton-mcp-pro/tools")
    from live_client import live, batch, ref, events, tracks, track_by_name, set_param

    live("get_arrangement_info")
    live("create_arrangement_midi_clip", {"track_index": 2, "time": 16.0, "length": 4.0, "notes": [...]})
    set_param(track, device, "Dry/Wet", 0.3)      # by parameter name, normalized 0-1

    # many commands, one round trip and one Live tick; ref() uses an earlier result
    batch([("create_midi_track", {"index": -1}),
           ("set_track_name", {"track_index": ref(0, "index"), "name": "Bass"})])

    for ev in events():                           # clip launches, transport, tempo... as they happen
        print(ev["type"], ev)

Every command takes 0.4-1.5 s (Live gives the script's threads time between its ticks), so
batch what you can and never call this from anything time-critical; send MIDI for that
(live_midi.py). Moved here from midigenai, where it grew during the jam work (see that repo's
docs/JAM_ENGINEERING_NOTES.md).
"""

from __future__ import annotations

import json
import socket
import threading

PORT = 9877


class LiveError(RuntimeError):
    pass


class _Conn:
    """One persistent socket per port (the Remote Script serves many commands per connection)."""

    def __init__(self, port: int):
        self.port = port
        self.sock: socket.socket | None = None
        self.lock = threading.Lock()

    def _connect(self):
        sk = socket.socket()
        try:
            sk.connect(("localhost", self.port))
        except OSError as e:
            sk.close()
            raise LiveError(f"can't reach Live on localhost:{self.port} — is Live running with the "
                            f"AbletonMCP control surface enabled? ({e})") from e
        self.sock = sk

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def request(self, cmd: str, params: dict, timeout: float) -> dict:
        with self.lock:
            for attempt in (0, 1):
                fresh = self.sock is None
                if fresh:
                    self._connect()
                try:
                    return self._roundtrip(cmd, params, timeout)
                except (ConnectionError, BrokenPipeError, EOFError):
                    # A stale connection (Live restarted, script reloaded): retry once on a new one
                    self.close()
                    if fresh or attempt:
                        raise
                except BaseException:
                    self.close()
                    raise
        raise AssertionError("unreachable")

    def _roundtrip(self, cmd: str, params: dict, timeout: float) -> dict:
        sk = self.sock
        sk.settimeout(timeout)
        sk.sendall(json.dumps({"type": cmd, "params": params}).encode())
        buf = b""
        while True:
            chunk = sk.recv(1 << 20)
            if not chunk:
                raise EOFError("Live closed the connection")
            buf += chunk
            try:
                return json.loads(buf)
            except ValueError:
                continue


_conns: dict[int, _Conn] = {}


def live(cmd: str, params: dict | None = None, timeout: float = 30.0, port: int = PORT):
    """Send one command, return its `result` (raises LiveError on error)."""
    conn = _conns.setdefault(port, _Conn(port))
    try:
        r = conn.request(cmd, params or {}, timeout)
    except socket.timeout as e:
        raise LiveError(f"{cmd}: no answer from Live in {timeout:.0f} s") from e
    except OSError as e:
        raise LiveError(f"{cmd}: connection to Live failed ({e})") from e
    if r.get("status") == "error":
        raise LiveError(f"{cmd}: {r.get('message')}")
    return r.get("result", r)


def ref(i: int, *keys) -> dict:
    """Use command i's result in a later batch command: ref(0, "index") -> result[0]["index"]."""
    return {"$ref": [i, *keys]}


def batch(commands: list, stop_on_error: bool = True, port: int = PORT) -> list:
    """Run [(cmd, params), ...] or [{"type", "params"}, ...] in one round trip and one Live tick.

    Returns the results in order; raises LiveError naming the first failed command (the ones
    before it did run). With stop_on_error=False, returns every entry's {"status", ...} instead.
    """
    cmds = [c if isinstance(c, dict) else {"type": c[0], "params": c[1] if len(c) > 1 else {}}
            for c in commands]
    r = live("batch", {"commands": cmds, "stop_on_error": stop_on_error},
             timeout=max(30.0, 0.5 * len(cmds) + 10), port=port)
    results = r["results"]
    if not stop_on_error:
        return results
    for i, res in enumerate(results):
        if res["status"] != "success":
            raise LiveError(f"batch command {i} ({cmds[i]['type']}): {res.get('message')}")
    return [res["result"] for res in results]


def events(since: int | None = None, wait: float = 10.0, port: int = PORT):
    """Yield Live events (clip launches, transport, tempo, selection, mute/solo/arm...) as they
    happen, forever. since=None starts from now; 0 replays what's still buffered.

    Uses its own connection so a long poll doesn't hold up live() calls from other threads.
    """
    conn = _Conn(port)
    try:
        if since is None:
            since = conn.request("get_events", {"since": 1 << 62}, 10.0)["result"]["latest"]
        while True:
            r = conn.request("get_events", {"since": since, "timeout": wait}, wait + 10.0)
            if r.get("status") == "error":
                raise LiveError(f"get_events: {r.get('message')}")
            res = r["result"]
            if res.get("missed"):
                yield {"type": "missed", "since": since}
            yield from res["events"]
            since = res["events"][-1]["seq"] if res["events"] else max(since, res["latest"])
            if res["latest"] < since:
                since = res["latest"]  # Live restarted: its counter began again
    finally:
        conn.close()


def tracks() -> list[dict]:
    """[{index, name, arm, input, output, devices, arrangement_clips}] for every track."""
    n = int(live("get_session_info").get("track_count", 0))
    if not n:
        return []
    res = batch([c for i in range(n) for c in (("get_track_info", {"track_index": i}),
                                                ("get_track_routing", {"track_index": i}),
                                                ("get_arrangement_clips", {"track_index": i}))],
                stop_on_error=False)
    out = []
    for i in range(n):
        t, r, c = (x.get("result") or {} for x in res[3 * i:3 * i + 3])
        out.append({"index": i, "name": t.get("name"), "arm": bool(t.get("arm")),
                    "input": r.get("input_routing_type"), "output": r.get("output_routing_type"),
                    "devices": [d["name"] for d in t.get("devices", [])],
                    "arrangement_clips": len(c.get("clips", []))})
    return out


def track_by_name(name: str) -> int | None:
    n = int(live("get_session_info").get("track_count", 0))
    for i in range(n):
        if live("get_track_info", {"track_index": i}).get("name") == name:
            return i
    return None


def clear_arrangement_clips(track: int, start_at: float = 0.0) -> int:
    """Delete arrangement clips on `track` starting at or after `start_at` beats."""
    clips = live("get_arrangement_clips", {"track_index": track}).get("clips", [])
    n = 0
    for i in range(len(clips) - 1, -1, -1):
        if clips[i]["start_time"] >= start_at:
            live("delete_arrangement_clip", {"track_index": track, "arrangement_clip_index": i})
            n += 1
    return n


def arrangement_notes(track: int) -> list[dict]:
    """All notes on a track's arrangement lane with ABSOLUTE beat positions
    ({pitch, start, duration, velocity, clip_start})."""
    clips = live("get_arrangement_clips", {"track_index": track}).get("clips", [])
    out = []
    for i, c in enumerate(clips):
        notes = live("get_arrangement_clip_notes",
                     {"track_index": track, "arrangement_clip_index": i}).get("notes", [])
        for n in notes:
            out.append({"pitch": n["pitch"], "start": c["start_time"] + n["start_time"],
                        "duration": n.get("duration", 0.0), "velocity": n.get("velocity", 0),
                        "clip_start": c["start_time"]})
    return sorted(out, key=lambda n: n["start"])


def set_param(track: int, device: int, name: str, value: float) -> bool:
    """Set a device parameter by name (normalized 0-1). Tries `name` and the
    slash-less spelling (Echo: 'Dry Wet', Reverb: 'Dry/Wet')."""
    params = live("get_device_parameters",
                  {"track_index": track, "device_index": device}).get("parameters", [])
    for i, prm in enumerate(params):
        if prm.get("name") in (name, name.replace("/", " ")):
            live("set_device_parameter", {"track_index": track, "device_index": device,
                                          "parameter_index": prm.get("index", i), "value": value})
            return True
    return False
