# tools/

Helper scripts that compose with the Ableton MCP server but run as their own
processes. The agent (or you) drives them via shell, no MCP server changes.

## midigenai_bridge.py — AI MIDI continuation

CLI that turns Ableton clip notes into an AI-generated continuation. Wraps
the [`midigenai`](https://github.com/nicholasbien/midigenai) package
(a 113M custom transformer, event-based tokenization; `v2-100m` by default). The model
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
