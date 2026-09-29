# Ableton MCP Pro - Next Steps

Roadmap for achieving full Ableton control via MCP.

## Completed

### Core Clip & Track Management
- [x] **Delete clip** — `delete_clip(track_index, clip_index)`
- [x] **Create audio track** — `create_audio_track(index)`
- [x] **Delete track** — `delete_track(track_index)`
- [x] **Duplicate clip** — `duplicate_clip(track_index, clip_index, target_index)`
- [x] **Duplicate track** — `duplicate_track(track_index)`
- [x] **Delete device** — `delete_device(track_index, device_index)`
- [x] **Set clip loop** — `set_clip_loop(track_index, clip_index, loop_start, loop_end, looping)`
- [x] **Get clip notes** — `get_clip_notes(track_index, clip_index)`

### Mixing & Routing
- [x] **Set track volume** — `set_track_volume(track_index, volume)` (0.0-1.0)
- [x] **Set track panning** — `set_track_panning(track_index, panning)` (0.0-1.0, 0.5=center)
- [x] **Mute track** — `set_track_mute(track_index, mute)`
- [x] **Solo track** — `set_track_solo(track_index, solo)`
- [x] **Master/return track support** — `track_index: -1` for master, `-2`/`-3` for returns
- [x] **Arm track** — `set_track_arm(track_index, arm)`
- [x] **Send levels** — `set_send_level(track_index, send_index, value)`
- [x] **Set time signature** — `set_time_signature(numerator, denominator)`
- [x] **Metronome** — `set_metronome(on)`

### Transport & Scene Control
- [x] **Scene launch** — `fire_scene(scene_index)`
- [x] **Create scene** — `create_scene(index)`
- [x] **Delete scene** — `delete_scene(scene_index)`
- [x] **Set scene name** — `set_scene_name(scene_index, name)`

### Arrangement View
- [x] **Get arrangement info** — `get_arrangement_info()` — transport state, loop, tempo
- [x] **Set song time** — `set_song_time(time)` — with retry logic
- [x] **Set record mode** — `set_record_mode(on)`
- [x] **Set arrangement overdub** — `set_arrangement_overdub(on)`
- [x] **Set back to arranger** — `set_back_to_arranger()`
- [x] **Set arrangement loop** — `set_arrangement_loop(on, start, length)`
- [x] **Get arrangement clips** — `get_arrangement_clips(track_index)` — per-track
- [x] **Get full arrangement** — `get_full_arrangement()` — all tracks, scenes, tempo
- [x] **Record arrangement** — `record_arrangement(sections)` — beat-accurate with background threading

### Device Control
- [x] **Get device parameters** — `get_device_parameters(track_index, device_index)`
- [x] **Set device parameter** — `set_device_parameter(track_index, device_index, parameter_index, value)`
- [x] **Batch set device parameters** — `batch_set_device_parameters(...)`
- [x] **Load instrument/effect** — `load_instrument_or_effect(track_index, uri, clip_index)`

### Automation
- [x] **Set clip envelope** — `set_clip_envelope(track_index, clip_index, device_index, parameter_index, points)` — smooth interpolated ramps
- [x] **Get clip envelope** — `get_clip_envelope(track_index, clip_index, device_index, parameter_index)` — read automation data
- [x] **Clear clip envelope** — `clear_clip_envelope(track_index, clip_index, device_index, parameter_index)`

### Advanced
- [x] **Undo** — `undo()`
- [x] **Redo** — `redo()`

---

## Known Limitations

### Arrangement Clips Are Read-Only
The LOM cannot create, delete, or modify arrangement clips directly. The only way to populate the arrangement is by recording session clips into it using `record_arrangement`. To erase content, record an empty scene over the region.

### Recording Timing (Solved)
Scene transitions previously drifted ~4 beats due to `do_on_main` round-trip latency causing late fires that quantization pushed to the next bar. Fixed by using `fire_and_forget` (no round-trip wait) + 1-bar quantization. Scenes now fire 2 beats before the target boundary; quantization snaps to the correct bar. Pre-scheduling via `schedule_message(ticks, fn)` was also tried but failed — the tick rate is unreliable and caused early fires.

### Audio Clip Loading
- `browser.load_item()` works for instruments/effects but .alc audio clips only load device chains, not the audio clip itself
- `ClipSlot.create_clip()` in the Remote Script API only accepts a `double` (length for MIDI clips), not file paths
- The file-path-based audio clip creation may be Max for Live specific
- **Workaround**: manually drag audio clips from Ableton's browser

### Stale Song Reference
After Ableton restarts or swaps documents, cached `self._song` becomes invalid. Fixed by refreshing `self._song = self.song()` at the start of every `_process_command`, but the first command after a restart may still fail (retry works).

---

## Remaining Work

### High Priority: Recording Accuracy
- [x] **Clip trigger quantization** — `record_arrangement` now sets `song.clip_trigger_quantization = 4` (1 Bar) before recording and restores original value after. Scene fires snap to bar boundaries.
- [x] **Fire-and-forget scene fires** — Scene fires use `schedule_message(0, fn)` without waiting for round-trip completion. Eliminates `do_on_main` latency that caused late fires + quantization drift.
- [x] **Auto-disarm tracks** — All tracks disarmed before recording to prevent stray MIDI input during erase or recording.
- [x] **Cancellation support** — Scheduled callbacks check a `cancelled` flag; set on error to prevent stale scene fires.
- [x] **Play arrangement** — `play_arrangement(time)` stops session clips, switches to arrangement view, and plays from a position.
- [ ] **Verify recording results** — After `record_arrangement`, automatically call `get_full_arrangement` and validate clip boundaries match expected positions.

### Audio Support
- [ ] **Investigate Max for Live API** — M4L may expose `ClipSlot.create_clip(file_path)` for audio files. Could add an M4L device as a bridge.
- [ ] **Audio clip from file** — If M4L bridge works, `create_audio_clip(track_index, clip_index, file_path)` for wav/aiff/flac/mp3

### Mixing & Routing
- [ ] **Track routing** — `set_track_input/output(track_index, routing_type, channel)`

### Nice-to-Haves
- [ ] **Capture MIDI** — `song.capture_midi()`
- [ ] **Groove pool** — apply groove templates to clips
- [ ] **Cross-fader** — control crossfader assignment and position
- [ ] **Arrangement automation** — Currently automation only applies to session clips and gets baked in during recording. Direct arrangement envelope editing would require M4L. Deleting it works offline: `tools/als.py clear-automation SET.als TRACK [--param volume|pan|all] [--db N] -o OUT.als` (close the set first, reopen after).

---

## MCP Limitations for Music Skills

The following MCP capabilities are missing and limit what music production skills can fully execute. Listed in priority order by how many skills they'd unlock.

### Priority 1: Rack Creation & Chain Management

**What's missing:** No way to create Instrument Racks or Audio Effect Racks with multiple chains (e.g., Dry/Wet parallel processing, layered instrument patches).

**Skills blocked:**
- **growl-bass** — Needs Dry (clean sub) + Wet (growl) chains with inverted macro control
- **reese-bass** — Needs Instrument Rack to layer saw oscillators + sine sub as separate chains
- **supersaw-chords** — Needs Instrument Rack for mono center layer + stereo width layer + noise layer
- **synthwave** — Needs Audio Effect Rack for parallel Dry/Wet gated reverb snare
- **dub-techno** — Needs multi-chain racks for effect layering

**How to implement:** The Remote Script API exposes `Track.devices` and rack internals. Key LOM objects:
- `RackDevice.chains` — list of chains in a rack
- `RackDevice.create_chain()` — add a chain (may need investigation)
- `Chain.devices` — devices within a chain
- Alternatively: load a pre-built rack template from the browser, then modify its devices/parameters

**Workaround today:** Load effects in series on a single chain (loses the parallel Dry/Wet routing). Or use multiple tracks panned/routed to achieve the same result.

### Priority 2: MIDI Effect Loading

**What's missing:** Unclear if `load_instrument_or_effect` can load MIDI effects (Chord, Scale, Arpeggiator) — these live in a different part of Ableton's device chain (before the instrument).

**Skills blocked:**
- **supersaw-chords** — Uses Chord MIDI effect for automatic octave doubling
- **synthwave** — Uses Arpeggiator MIDI effect for 16th note arps
- **trance-melodies** — References Scale MIDI effect for staying in key
- **ukg-drums** — References Scale for percussion tuning

**How to implement:** Test if `browser.load_item()` works for MIDI effects found under the MIDI Effects browser category. If not, may need a dedicated `load_midi_effect` command that inserts before the instrument in the chain.

**Workaround today:** Program the notes manually (e.g., write octave-doubled notes instead of using Chord device, write arpeggiated patterns instead of using Arpeggiator).

### Priority 3: Return Track Creation

**What's missing:** `set_send_level` exists but there's no way to create new return tracks or load effects onto them. Returns use `track_index: -2, -3, etc.` but only if they already exist.

**Skills blocked:**
- **ukg-drums** — Send 1 (Drum Bus) + Send 2 (Redux) processing architecture
- **dub-techno** — Multi-send reverb architecture (2-3 reverb returns)
- **house-drums** — Parallel compression on a return track
- **techno-drums** — Short dark reverb + ping-pong delay sends

**How to implement:** The LOM has `song.create_return_track()`. Add a `create_return_track()` MCP tool that creates a return and returns its index. Then effects can be loaded via `load_instrument_or_effect(track_index=-2, ...)`.

**Workaround today:** Use insert effects instead of sends (less flexible but functional).

### Priority 4: Groove Pool / Swing Templates

**What's missing:** No way to apply groove templates from Ableton's Groove Pool to clips.

**Skills blocked:**
- **drum-swing** — References MPC groove templates at specific percentages
- **ukg-drums** — MPC 16th swing at 60-70% depth
- **house-drums** — 54-58% swing on hats/percussion

**How to implement:** The LOM has `Clip.groove` property and groove pool access. Add `apply_groove(track_index, clip_index, groove_name, amount)` tool.

**Workaround today:** Manually nudge notes off-grid using specific timing offsets in `add_notes_to_clip`.

### Priority 5: Slice Audio to MIDI

**What's missing:** No way to slice an audio clip into a Drum Rack with individual hits mapped to pads.

**Skills removed due to this:**
- **dnb-drums** — Core workflow is slicing the Amen break
- **breakbeat** — Core workflow is chopping breaks at house tempo

**How to implement:** This is complex — likely requires:
1. Detecting transients in audio (may need M4L or external processing)
2. Creating a Drum Rack with Simpler instances
3. Setting each Simpler's sample start/end points

**Workaround today:** These skills were removed. Users can slice manually in Ableton, then use MCP to program patterns on the resulting Drum Rack.

### Priority 6: Macro Mapping

**What's missing:** No way to map device parameters to Rack macro knobs.

**Skills blocked:**
- **growl-bass** — Maps Oscillator D level to Macro 1 for performance control
- **dub-techno** — Macro-controlled effect parameters

**How to implement:** `RackDevice.macros_mapped` and macro mapping is accessible through the LOM but complex to set up programmatically.

**Workaround today:** Use clip automation on the specific parameter instead of macro mapping.
