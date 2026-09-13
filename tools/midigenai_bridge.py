"""
MIDI Gen AI Bridge: Ableton MCP clip notes -> AI MIDI generation -> notes back.

Uses the [midigenai](https://github.com/nicholasbien/midigenai) package directly;
the model is downloaded from HuggingFace on first use and cached locally.

Reads JSON config from stdin:
  {
    "notes": [{"pitch": 62, "start_time": 0.0, "duration": 0.5, "velocity": 100}, ...],
    "tempo_bpm": 80.0,
    "max_new_tokens": 256, "temperature": 1.2, "top_k": 50,
    "prompt_end_beat": 32.0,           # filter output to notes after this beat
    "pitch_range": [60, 96],           # optional pitch filter
    "version": "v2-100m",              # which subfolder of the HF repo to load
                                       # (default: $MIDIGENAI_VERSION env var, then midigenai's DEFAULT_VERSION)
    "repo_id": "nicholasbien/midigenai" # default: $MIDIGENAI_REPO_ID, then "nicholasbien/midigenai"
  }

Writes JSON to stdout:
  {"prompt_tokens": int, "generated_tokens": int, "tempo_bpm": float,
   "notes": [{"pitch", "start_time", "duration", "velocity"}, ...]}

Switching to a new model release in the future:
  1. Push the new model to a new subfolder on the HF repo
  2. Either bump `MIDIGENAI_VERSION` env var (no code change), pass
     `"version"` in the JSON payload, or update midigenai's
     `hub.py::DEFAULT_VERSION`. Whichever is most convenient.

Run with whatever Python env has the `[ai]` extras installed:
  pip install "ableton-mcp-pro[ai]"
  python tools/midigenai_bridge.py < cfg.json
"""

import json
import sys
import tempfile
from pathlib import Path

TPQ = 480

# Lazy global so repeated calls in the same process don't reload the model
_GENERATOR = None


def _get_generator(repo_id, version):
    """Cache one generator per (repo_id, version) tuple."""
    global _GENERATOR
    cache_key = (repo_id, version)
    if _GENERATOR is None or _GENERATOR[0] != cache_key:
        from midigenai import load_from_hub
        gen = load_from_hub(version=version, repo_id=repo_id)
        _GENERATOR = (cache_key, gen)
    return _GENERATOR[1]


def notes_to_score(notes, tempo_bpm):
    from symusic import Score, Track, Note, Tempo
    score = Score(TPQ)
    score.tempos = [Tempo(time=0, qpm=tempo_bpm)]

    by_program = {}
    for n in notes:
        prog = int(n.get("program", 0))
        by_program.setdefault(prog, []).append(n)

    for prog, ns in by_program.items():
        track = Track(program=prog, is_drum=False, name=f"prog{prog}")
        for n in ns:
            track.notes.append(Note(
                time=int(round(float(n["start_time"]) * TPQ)),
                duration=max(1, int(round(float(n["duration"]) * TPQ))),
                pitch=int(n["pitch"]),
                velocity=int(n["velocity"]),
            ))
        score.tracks.append(track)
    return score


def score_to_notes(score, prompt_end_beat=None, pitch_range=None):
    notes = []
    tpq = score.ticks_per_quarter
    for track in score.tracks:
        for n in track.notes:
            start_beat = float(n.start) / tpq
            dur_beat = float(n.duration) / tpq
            pitch = int(n.pitch)
            if prompt_end_beat is not None and start_beat < prompt_end_beat - 1e-6:
                continue
            if pitch_range is not None and not (pitch_range[0] <= pitch <= pitch_range[1]):
                continue
            notes.append({
                "pitch": pitch,
                "start_time": round(start_beat - (prompt_end_beat or 0), 4),
                "duration": round(dur_beat, 4),
                "velocity": int(n.velocity),
                "mute": False,
            })
    notes.sort(key=lambda x: (x["start_time"], x["pitch"]))
    return notes


def main():
    cfg = json.loads(sys.stdin.read())

    notes = cfg["notes"]
    tempo = float(cfg.get("tempo_bpm", 120.0))
    max_new_tokens = int(cfg.get("max_new_tokens", 256))
    temperature = float(cfg.get("temperature", 1.2))
    top_k = int(cfg.get("top_k", 50))
    prompt_end_beat = cfg.get("prompt_end_beat")
    if prompt_end_beat is not None:
        prompt_end_beat = float(prompt_end_beat)
    pitch_range = cfg.get("pitch_range")
    # version/repo_id default to None — midigenai resolves env vars + DEFAULT_VERSION
    version = cfg.get("version")
    repo_id = cfg.get("repo_id")

    score = notes_to_score(notes, tempo)
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
        in_path = f.name
    score.dump_midi(in_path)

    gen = _get_generator(repo_id, version)
    prompt_ids = gen.encode_midi_file(in_path)

    out_path = in_path.replace(".mid", "_out.mid")
    new_ids = gen.generate_to_midi(
        prompt_ids, out_path,
        tempo_bpm=tempo,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
        top_k=top_k,
    )

    from symusic import Score
    out_score = Score(out_path)
    out_notes = score_to_notes(out_score, prompt_end_beat=prompt_end_beat, pitch_range=pitch_range)

    Path(in_path).unlink(missing_ok=True)
    Path(out_path).unlink(missing_ok=True)

    json.dump({
        "prompt_tokens": len(prompt_ids),
        "generated_tokens": len(new_ids),
        "tempo_bpm": tempo,
        "notes": out_notes,
    }, sys.stdout)


if __name__ == "__main__":
    main()
