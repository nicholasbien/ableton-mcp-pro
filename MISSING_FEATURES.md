# Missing Features — Things the LOM Can Do That We Haven't Implemented

Exhaustive list of Ableton LOM capabilities we're not exposing yet, grouped by category. Everything here is technically possible — the API exists, we just haven't built the tool.

---

## Clip Editing

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Remove notes** | `clip.remove_notes_extended(from_pitch, pitch_span, from_time, time_span)` | Can't delete specific notes — must clear and rewrite entire clip |
| **Quantize notes** | `clip.quantize(grid, strength)` | Can't snap sloppy notes to grid. Must manually calculate correct positions |
| **Quantize pitch** | `clip.quantize_pitch(pitch, grid, strength)` | Can't quantize a single pitch independently |
| **Duplicate loop** | `clip.duplicate_loop()` | Can't double a loop with one call — must read notes, calculate, rewrite |
| **Duplicate region** | `clip.duplicate_region(start, length, dest, pitch, transposition)` | Can't copy a section of notes within a clip with transposition |
| **Crop clip** | `clip.crop()` | Can't trim clip to loop boundaries |
| **Clip color** | `clip.color` / `clip.color_index` (get/set) | Can't set clip colors for visual organization |
| **Clip mute** | `clip.muted` (get/set) | Can't mute individual clips (only tracks) |
| **Clip launch mode** | `clip.launch_mode` (get/set) | Can't set trigger/gate/toggle/repeat launch behavior |
| **Clip launch quantization** | `clip.launch_quantization` (get/set) | Can't set per-clip launch quantization |
| **Clip legato** | `clip.legato` (get/set) | Can't enable legato mode on clips |
| **Start/end markers** | `clip.start_marker` / `clip.end_marker` (get/set) | Can't adjust clip start/end independent of loop points |
| **Per-clip time signature** | `clip.signature_numerator` / `signature_denominator` | Can't set time signature per clip |
| **Follow actions** | `clip.follow_action_*` properties | Can't set up automatic clip chaining for generative patterns |
| **Select/deselect notes** | `clip.select_all_notes()`, `clip.deselect_all_notes()`, `clip.get_selected_notes()` | Can't work with note selections |
| **RAM mode** | `clip.ram_mode` (get/set) | Can't toggle RAM vs disk streaming for audio clips |

## Audio Clip Specific

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Warp markers** | `clip.add_warp_marker(beat, sample)`, `clip.move_warp_marker(beat, sample)`, `clip.delete_warp_marker(beat)` (Live 11.0.5+) | Can't time-stretch, align, or warp audio clips programmatically |
| **Warp on/off** | `clip.warping` (get/set) | Can't enable/disable warping |
| **Warp mode** | `clip.warp_mode` (get/set) | Can't switch between Beats/Tones/Texture/Re-Pitch/Complex/Complex Pro |
| **Clip gain** | `clip.gain` (get/set) | Can't adjust audio clip gain (separate from track volume) |
| **Pitch shift** | `clip.pitch_coarse` / `clip.pitch_fine` (get/set) | Can't transpose audio clips |
| **Clip fades** | Fade in/out properties | Can't set crossfades on audio clips |
| **Sample info** | `clip.sample_length`, `clip.file_path`, `clip.sample_rate` | Can read but don't expose — useful for audio clip workflows |
| **Beat/sample time conversion** | `clip.beat_to_sample_time()`, `clip.sample_to_beat_time()` | Can't convert between beat and sample positions |

## Song / Transport

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Capture MIDI** | `song.capture_midi()` | Can't capture recently played MIDI into a clip (Live's "Capture" feature) |
| **Capture and insert scene** | `song.capture_and_insert_scene()` | Can't snapshot currently playing clips as a new scene |
| **Stop all clips** | `song.stop_all_clips(quantized)` | Can't stop all clips at once (must stop individually) |
| **Tap tempo** | `song.tap_tempo()` | Can't tap tempo programmatically |
| **Jump by** | `song.jump_by(amount)` | Can't move playhead relatively (must calculate absolute position) |
| **Scrub** | `song.scrub_by(amount)` | Can't scrub playhead |
| **Cue points** | `song.set_or_delete_cue()`, `song.jump_to_next_cue()`, `song.jump_to_prev_cue()` | Can't create, delete, or navigate cue/locator points |
| **Global swing** | `song.swing_amount` (get/set) | Can't set global swing amount |
| **Global groove** | `song.groove_amount` (get/set) | Can't set global groove depth |
| **Count-in** | `song.count_in_duration` (get/set) | Can't set count-in length |
| **Exclusive arm** | `song.exclusive_arm` (get/set) | Can't toggle exclusive arm mode |
| **Tempo nudge** | `song.nudge_down` / `song.nudge_up` | Can't nudge tempo for DJ-style mixing |
| **Punch in/out** | `song.punch_in` / `song.punch_out` (get/set) | Can't set punch recording boundaries |
| **Session record** | `song.session_record` (get/set) | Can't enable session recording mode |
| **Session automation record** | `song.session_automation_record` (get/set) | Can't enable session automation recording |
| **Re-enable automation** | `song.re_enable_automation()` | Can't re-enable automation after manual override |
| **Global scale** | `song.scale_name` / `song.scale_intervals` (get/set) | Can't set the global scale (for Push, clip view) |
| **Trigger session record** | `song.trigger_session_record(length)` | Can't trigger fixed-length session recording |
| **Continue playing** | `song.continue_playing()` | Can't resume from current position (only start from beginning) |

## Track Management

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Create return track** | `song.create_return_track()` | Can't create return tracks — must exist already to use sends |
| **Delete return track** | `song.delete_return_track(index)` | Can't remove return tracks |
| **Track color** | `track.color` / `track.color_index` (get/set) | Can't color-code tracks |
| **Track input routing** | `track.input_routing_type`, `track.input_routing_channel` | Can't set MIDI/audio input source |
| **Track output routing** | `track.output_routing_type`, `track.output_routing_channel` | Can't route output to other tracks or sends |
| **Available routings** | `track.available_input_routing_types`, etc. | Can't list what routing options exist |
| **Monitoring state** | `track.current_monitoring_state` (get/set) | Can't switch between In/Auto/Off monitoring |
| **Track grouping** | `track.group_track`, `track.is_foldable`, `track.fold_state` | Can't create/manage track groups |
| **Track freeze** | `track.freeze()` / `track.unfreeze()` | Can't freeze tracks to save CPU |
| **Track flatten** | `track.flatten()` | Can't flatten frozen tracks to audio |
| **Track delay** | Track delay compensation in samples | Can't set per-track delay for timing alignment |
| **Scene color** | `scene.color` / `scene.color_index` (get/set) | Can't color-code scenes |
| **Scene tempo** | `scene.tempo` (get/set) | Can't set per-scene tempo changes |
| **Scene time signature** | `scene.time_signature_*` | Can't set per-scene time signature |
| **Duplicate scene** | `song.duplicate_scene(index)` | Can't duplicate an entire scene row |

## Mixer / Crossfader

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Crossfader position** | `song.master_track.mixer_device.crossfader` | Can't control the crossfader |
| **Crossfader assignment** | `track.mixer_device.crossfade_assign` (get/set) | Can't assign tracks to A/B crossfader sides |
| **Cue volume** | `song.master_track.mixer_device.cue_volume` | Can't set preview/cue volume |
| **Pre/post fader sends** | Send pre/post toggle | Can't switch sends between pre and post fader |

## Devices & Racks

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Device on/off** | `device.is_active` (get/set) | Can't enable/disable individual devices |
| **Rack chains** | `RackDevice.chains`, `RackDevice.create_chain()` | Can't create parallel processing chains |
| **Chain devices** | `chain.devices` | Can't add/control devices within rack chains |
| **Macro mapping** | Rack macro properties | Can't map parameters to macro knobs |
| **Plugin windows** | Show/hide plugin GUI windows | Can't toggle plugin editor visibility |
| **Device presets** | Store/recall preset banks | Can't save or load device presets |
| **SimplerDevice** | `simpler.sample`, playback mode, start/end | Can't control Simpler sample parameters |
| **DrumPad access** | `DrumRackDevice.drum_pads`, `DrumPad.chains` | Can't query or modify individual drum pads |
| **MIDI effects** | Load Chord, Scale, Arpeggiator, etc. | Untested — may work via `load_instrument_or_effect` but never verified |

## Groove Pool

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Apply groove** | `clip.groove` property | Can't apply MPC/Live groove templates to clips |
| **Groove pool access** | Groove pool objects | Can't browse or manage groove templates |

## View / Navigation

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Show view** | `app.view.show_view(identifier)` | Can't switch between Session/Arrangement/Detail views |
| **Focus view** | `app.view.focus_view(identifier)` | Can't focus specific panels |
| **Scroll to track** | View navigation | Can't scroll to a specific track or clip |
| **Zoom** | View zoom properties | Can't control zoom level |

## Live 12 Specific

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Take lanes** | Take lane management (Live 12+) | Can't create or manage take lanes for comping |
| **MIDI transformations** | New Live 12 MIDI tools | Can't use Live 12's MIDI transformation features |

## Other

| Feature | LOM API | Impact |
|---------|---------|--------|
| **Send MIDI messages** | MIDI output functions | Can't send raw MIDI CC/Program Change messages |
| **Clip annotations** | Clip info text | Can't read/write clip annotation text |
| **Track annotations** | Track info text | Can't read/write track annotation text |
| **Application info** | `app.get_major_version()`, etc. | Can't detect Ableton version for feature compatibility |
| **Listeners/observers** | `add_*_listener()` for all properties | Can't set up real-time callbacks when things change (e.g., playback position, clip triggers) |

---

## Priority Ranking

What would have the most impact if implemented:

### Tier 1 — Would significantly improve production workflows
1. **Remove notes** — essential for editing, currently must rewrite entire clips
2. **Create return track** — unlocks send/return mixing architecture
3. **Capture MIDI** — hugely useful for jamming workflows
4. **Warp markers** — unlocks audio clip time-stretching and alignment
5. **Device on/off** — basic mixing operation, can't bypass effects
6. **Rack chains** — unlocks parallel processing, layered instruments
7. **Stop all clips** — basic transport operation
8. **Quantize notes** — instant cleanup of programmed patterns

### Tier 2 — Nice quality-of-life improvements
9. **Clip/track/scene colors** — visual organization
10. **Audio clip gain/pitch** — adjust audio without track-level changes
11. **Groove pool / global swing** — better than manual note nudging
12. **Follow actions** — generative patterns, automatic clip progression
13. **Duplicate scene** — faster scene-based workflow
14. **Track input/output routing** — sidechain, resampling setups
15. **Monitoring state** — important for recording workflows
16. **Cue points** — arrangement navigation
17. **MIDI effect loading** — Chord, Arpeggiator, Scale devices

### Tier 3 — Specialized use cases
18. **DrumPad/SimplerDevice** — drum rack programming
19. **Track grouping** — organize large projects
20. **Track freeze/flatten** — CPU management
21. **Crossfader** — DJ/performance workflows
22. **View/navigation** — UI control
23. **Take lanes** — comping workflows
24. **Clip launch modes** — performance setups
