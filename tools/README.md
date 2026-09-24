# tools/

Helper scripts that compose with the Ableton MCP server but run as their own
processes. The agent (or you) drives them via shell, no MCP server changes.

## midigenai_bridge.py — AI MIDI continuation

CLI that turns Ableton clip notes into an AI-generated continuation. Wraps
the [`midigenai`](https://github.com/nicholasbien/midigenai) package
(a 113M custom transformer, event-based tokenization; `v3` by default). The model
is auto-downloaded from
[huggingface.co/nicholasbien/midigenai](https://huggingface.co/nicholasbien/midigenai)
on first use and cached at `~/.cache/huggingface/`.

### Setup

```bash
pip install "ableton-mcp-pro[ai]"
```

That installs `midigenai`, `torch`, `miditok`, `symusic`, and
`huggingface_hub`. No separate repo clone, no extra venv.

### What it does

```
JSON notes (stdin)
    ↓
build a temporary .mid file
    ↓
encode with the v2 MidiTok tokenizer
    ↓
sample N tokens from the v2 transformer (downloaded from HF on first call)
    ↓
decode back to MIDI, drop everything ≤ prompt_end_beat
    ↓
JSON notes (stdout)
```

### Usage

```bash
echo '{
  "notes": [
    {"pitch": 74, "start_time": 0,  "duration": 1, "velocity": 95},
    {"pitch": 78, "start_time": 1,  "duration": 1, "velocity": 95},
    {"pitch": 81, "start_time": 2,  "duration": 2, "velocity": 100}
  ],
  "tempo_bpm": 80,
  "max_new_tokens": 256,
  "temperature": 1.2,
  "top_k": 50,
  "prompt_end_beat": 4.0,
  "pitch_range": [60, 92]
}' | python tools/midigenai_bridge.py
```

Returns:

```json
{
  "prompt_tokens": 33,
  "generated_tokens": 256,
  "tempo_bpm": 80,
  "notes": [{"pitch": 78, "start_time": 0.0, "duration": 0.5, "velocity": 95, "mute": false}, ...]
}
```

Note start times are returned **relative to `prompt_end_beat`** so the result
drops cleanly into a fresh clip starting at beat 0.

### Knobs

| key | meaning |
|---|---|
| `notes` | seed notes — Ableton MCP format (`pitch`/`start_time`/`duration`/`velocity`) |
| `tempo_bpm` | tempo of seed *and* output (the model is tempo-agnostic; this is just decoding) |
| `max_new_tokens` | how much continuation to sample. ~4 tokens/note → 256 ≈ 60 notes |
| `temperature` | 0.5–1.5. Lower sticks closer to the prompt; higher diverges more |
| `top_k` | nucleus sampling K |
| `prompt_end_beat` | drop output notes that start before this beat (= filter out the prompt itself) |
| `pitch_range` | optional `[min, max]` MIDI pitch filter — useful when you only want, say, the lead range |
| `version` | which subfolder of the HF repo to load. Defaults to `MIDIGENAI_VERSION` env var, then `v2-100m`. |
| `repo_id` | HF model repo. Defaults to `MIDIGENAI_REPO_ID` env var, then `nicholasbien/midigenai`. |

### Switching to a new model release

Three ways to point the bridge at a different version, in increasing scope:

```bash
# 1) Per-call (just for one generation):
echo '{ "notes": [...], "version": "v2" }' | python tools/midigenai_bridge.py

# 2) Per shell session:
export MIDIGENAI_VERSION=v2
python tools/midigenai_bridge.py < cfg.json

# 3) Permanent: bump DEFAULT_VERSION in midigenai/hub.py
```

To see what's published:

```python
from midigenai import list_hub_versions
list_hub_versions()         # ['v2-100m', 'v2-pilot']  # 100M is the current default
```

Adding a new version on the model author side = upload `ckpt_final.pt` and
`tokenizer.json` to a new subfolder of the HF model repo. No code changes
needed in midigenai or the bridge — both auto-discover.

### Wiring it into the Ableton workflow

The agent typically:

1. `mcp__AbletonMCP__get_clip_notes` → pull a clip's notes as the seed
2. Build a JSON payload with those notes + tempo + knobs
3. Run `tools/midigenai_bridge.py` via `Bash`, capture stdout
4. (optional) post-filter: snap to scale, clip durations, drop anything outside the song length
5. `mcp__AbletonMCP__create_clip` + `mcp__AbletonMCP__add_notes_to_clip` on a target track to drop the result

We deliberately did **not** add MCP tool wrappers around this. The bridge is a
plain CLI; the agent drives it via shell. Reasons:

- No MCP server restart needed when the bridge changes
- The bridge can be used standalone outside the agent (`echo … | python …`)
- The MCP server stays lean — `[ai]` is opt-in, not required

### Prompt design

v2 was trained on single-track polyphonic MIDI (heavy on piano via Lakh +
MAESTRO + POP909 + GiantMIDI). Best results come from:

- A monophonic or lightly-polyphonic **melodic seed** (4–8 bars, ~10–15 notes)
- Single instrument (omit `program` from notes, or all on the same program)
- Avoid feeding several stacked tracks (pad chords + bass + lead) — the model
  is happiest continuing a coherent musical phrase, not multi-part arrangements

### Performance

First call ≈ 2–4s on CPU (download + model load + ~250 tokens). Subsequent
calls in the same Python process reuse the loaded generator, so they run at
~70 notes/s. The bridge keeps the generator alive in a module-level cache.

## setup_jam_set.py — the Live side of a fluidclaude jam

Builds `you` (keyboard in, no instrument, MIDI To IAC Bus 3), `you (sound)`, `reply` (IAC Bus 2 /
Ch. 5) and, with `--loops bass:2,drums:10`, one track per fluidclaude loop channel; prints the
fluidclaude commands. Add an audio track "sc in" (Ext. In 1/2, Monitor In) yourself when the sc
engine plays into Live through BlackHole. Never leave `you` on All Ins: that includes the bus
fluidclaude plays on and every loop becomes a "call".

## live_client.py — talk to the Remote Script from a script

`live(cmd, params)` sends one command over the port-9877 socket and returns its result, plus
`tracks()`, `track_by_name(name)`, `clear_arrangement_clips(track)` and `set_param(track, device,
name, value)`. The same protocol the MCP server speaks, for scripts and tests that don't want an
MCP round trip (the resample and clip-tool tests were written against it). It keeps one
connection open and reconnects once if Live restarted.

Every call costs 0.2–1.5 s, most of it waiting for Live's next tick, so batch:

```python
from live_client import live, batch, ref, events

# one round trip, one Live tick; ref(i, key) is result i's key
idx = batch([("create_midi_track", {"index": -1}),
             ("set_track_name", {"track_index": ref(0, "index"), "name": "Bass"}),
             ("create_clip", {"track_index": ref(0, "index"), "clip_index": 0, "length": 4.0}),
             ("add_notes_to_clip", {"track_index": ref(0, "index"), "clip_index": 0, "notes": notes})])[0]["index"]

for ev in events():          # blocks; clip launches, transport, tempo, selection, mute/solo/arm...
    print(ev["type"], ev)
```

`batch` raises on the first failing command (the earlier ones did run); `stop_on_error=False`
runs them all and returns each `{status, result|message}`. Measured on Live 12.4: 10 reads 2.0 s
one by one vs 0.4 s batched, 10 writes 4.0 s vs 0.4 s. `record_arrangement`, `resample_master`
and `get_events` can't be batched.

`events()` long-polls `get_events` on its own connection and yields dicts with `seq`, `type`,
`time` (wall clock) and `beat` (song position when Live reported it). Types: `is_playing`,
`tempo`, `record_mode`, `signature_numerator`/`_denominator`, `loop`, `metronome`,
`arrangement_overdub` (all with `value`); `clip_fired` / `clip_playing` (`track_index`,
`clip_index`: slot, -1 stopped, -2 playing the arrangement); `track_mute`/`_solo`/`_arm`/`_name`;
`selected_track`, `selected_scene`; `tracks_changed`/`scenes_changed`/`return_tracks_changed`.
Live keeps the last 1000; a `missed` event means you fell further behind than that. Don't time
music from `beat` (it's read when the listener fires, and socket delivery adds 0.2 s+); follow
MIDI clock with `live_midi.Clock` for that.

`python tools/test_batch_events.py` checks both against a running Live, on scratch tracks it
deletes afterwards.

## live_midi.py — the fast path: MIDI in and out of Live

For anything timed. Notes out and Live's MIDI clock in over the macOS IAC buses (any CoreMIDI
port works), sub-millisecond instead of `live_client`'s 0.4–1.5 s per call. Use `live_client`
to set the set up, `live_midi` to play into it and follow its transport.

```bash
pip install "ableton-mcp-pro[midi]"          # mido + python-rtmidi (or: uv pip install mido python-rtmidi)
python tools/live_midi.py ports
python tools/live_midi.py clock "Bus 1"      # bpm / beat / bar while Live sends clock
python tools/live_midi.py note "Bus 2" 60 --vel 100 --dur 0.25 --ch 0
python tools/live_midi.py panic "Bus 2"
```

```python
from live_midi import open_out, Clock, play_pattern
out = open_out("Bus 2")              # substring; Live's spelling "IAC Driver (Bus 2)" works too
out.note(60, vel=100, dur=0.25)      # returns at once; the note-off is on a scheduler thread
out.cc(74, 64); out.program(5); out.panic()
clock = Clock("Bus 1")
clock.bpm, clock.beat, clock.playing
clock.next_beat(4.0)                 # block until the next bar line, then fire something
p = play_pattern(out, clock, notes, loop_beats=4.0, quantize_to=4.0)   # add_notes_to_clip schema
p.stop()
```

- **Clock**: in Live's MIDI preferences, turn Sync on for the output port (IAC Bus 1 in the jam
  setup). `beat` counts quarter notes from the song start: Start → 0, Song Position Pointer +
  Continue (what Live sends when you play from mid-song) → that position. It is interpolated
  between ticks; `bpm` averages the last 2 beats of ticks. `wait_until(beat)` wakes on ticks
  and sleeps the last stretch to the predicted time, so it lands between ticks (within ~0.1 ms
  of a steady clock in the tests), not on the next tick 20 ms later.
- **Units**: `Out.note(dur=)` is seconds; everything on `Clock` and `play_pattern` is beats.
  Channels are 0–15 (0 = Live's "Ch. 1").
- **`play_pattern`** waits for the transport, starts on the next `quantize_to` boundary, loops
  every `loop_beats` (or `loops=` times), skips `mute` notes, and releases its notes on `stop()`
  and, by default, when Live stops.
- **Latency**: a note through an IAC bus or rtmidi virtual port arrives ~0.1 ms after `send`
  (median, max ~0.3 ms, measured by `test_live_midi.py`). Live itself adds ~32 ms on tracks
  that monitor input (see the README's timing gotchas), which this module doesn't cancel.

`python tools/test_live_midi.py` tests the Clock with synthetic messages (no hardware), the
scheduler and `play_pattern` against a fake port, then loops notes and clock through an IAC bus
(the highest-numbered one, or `LIVE_MIDI_TEST_BUS`; it sends notes on channel 16 and a burst of
clock, so pick a bus nothing listens to) and an rtmidi virtual port. Live need not be running.
