---
name: mix-check
description: Measure a finished track against reference tracks and fix the gaps. Use when the user asks to check the mix, compare to a reference, make it club-ready, check loudness or LUFS, check the low end or sub, or asks why the track sounds dark, thin, quiet or muddy.
---

# Mix Check — Bounce, Measure Against References, Fix

## Quick Reference
- **Loop**: bounce (`resample_master`) → measure (`tools/mix_check.py`) → fix the biggest gap → bounce again
- **Compare drop to drop**: mix_check compares the loudest 30 s of each file, so quiet intros don't skew it
- **References**: 2-3 released tracks in the same genre; band balance is genre-specific (a Four Tet track had its sub 9 dB lower than a Daphni club track)
- **It measures, it doesn't listen**: numbers catch dark tops, weak subs, overs and stereo bass; the user's ears judge chords, groove and sound choice

## Step 1: Record and Bounce
1. `record_arrangement` with the section list (scene index + bars). Takes real time; nothing may touch Live meanwhile — a click in Live stops it
2. `resample_master` (no `seconds`: records to the last clip + 1 bar). Also real time. It mutes earlier bounce tracks itself and lists them in `muted_earlier_bounces` — an unmuted old bounce plays into the new take, doubles the mix and cancels the sub
3. The result's `file_path` is the AIFF in the project's `Samples/Recorded/`; copy it somewhere findable for the user

## Step 2: Measure
```
python tools/mix_check.py BOUNCE.aif --ref REF1.mp3 --ref REF2.wav --bpm 136 --sections 16,16,8,32,8,32,16
```
Needs the analysis extra: `pip install "ableton-mcp-pro[analysis]"`. About 10 s for a 4-minute track plus two references.

| Column | Meaning | Club target |
|---|---|---|
| LUFS | integrated loudness | drops -9 to -6; within ~1.5 LU of the refs |
| TP | true peak (4x oversampled) | at or below -0.3 dBTP; -1.0 for streaming |
| crest | peak minus RMS | 8-11 dB; under 7 = over-limited, flat |
| sub … air | band energy, dB relative to the total | within 3 dB of the refs (flagged otherwise) |
| mono | L/R correlation below 150 Hz | above 0.95; under 0.9 = stereo bass, collapses on club systems |

The per-section rows show where a problem lives (e.g. a breakdown with presence at -37 dB is muffled even if the drops are fine).

## Step 3: Fix, Biggest Gap First
Change sources before the master. Master EQ is a last 1-3 dB, not a rescue.

| Gap vs refs | Usual cause | Fix via MCP |
|---|---|---|
| presence / air low (dark) | snare, hats, synth top too quiet or filtered | raise snare/clap/hat/chord track volumes 1-2 dB; open Auto Filter cutoffs on synths; then master EQ Eight: bell +2 dB at 2.8 kHz (Q 0.8), high shelf +2.5 dB at 6 kHz |
| mid low | chords/lead buried | raise chord/lead tracks; high-pass bass layers so they stop masking 400 Hz-2 kHz |
| sub high, bass fine | sub track or kick tail too loud | lower the sub track 1-2 dB; shorten kick notes/decay |
| sub low | sub track quiet, or phase cancellation | check sub level; check nothing plays the same low part twice (old bounce tracks, duplicated clips) |
| mono < 0.95 | stereo spread on bass (Spread, chorus, wide presets) | Utility on bass tracks: Bass Mono On, Bass Freq 120 Hz; Operator Spread 0 on sub |
| TP over 0 / clipped | limiter catching only sample peaks | Limiter: Ceiling -1.0 dB, or lower Input Gain; reduce master Saturator drive |
| LUFS low | master too gentle | raise Limiter Input Gain in 1 dB steps; watch crest stay above 8 |
| LUFS high, crest < 8 | over-limited | lower Input Gain; the drop will hit harder, not quieter, on a club system |

## Pitfalls
- **Read parameter displays, not numbers**: `get_device_parameters` returns `display` ("-22 dB", "Saw D") and `items` for menus. Set by label or aim at a displayed value; a normalized guess once left a master Saturator at -22 dB
- **Session edits don't reach the arrangement**: clips recorded by `record_arrangement` are copies. After changing session clips or clip envelopes, record again. Mixer volumes, sends and device settings apply to the arrangement directly — those only need a re-bounce
- **One change set per bounce**: each bounce is minutes of real time; batch all fixes for the flagged gaps, then bounce once
- **Relative bands**: adding brightness lowers every other band's share of the total. When a band moves unexpectedly, compare absolute levels between two bounces before "fixing" it

## Build Order
1. Ask the user for 2-3 reference tracks in the genre (or find full-length files on disk)
2. `record_arrangement` with the section list; confirm clip ranges with `get_arrangement_clips`
3. `resample_master`; copy the file somewhere the user can find it
4. `tools/mix_check.py BOUNCE --ref ... --bpm ... --sections ...`
5. Fix the flagged gaps, largest first, using the table above (one batch)
6. Re-bounce and re-measure; stop when no gap exceeds 3 dB, TP ≤ -0.3 dBTP and mono ≥ 0.95
7. Tell the user what changed and ask them to listen — the numbers don't hear the music
