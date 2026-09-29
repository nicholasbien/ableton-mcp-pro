---
name: mixing-guide
description: Mix and master a track in Ableton. Use when the user asks about mixing, mastering, loudness, EQ, compression, side-chaining, reference tracks, or finalizing a track.
---

# Mixing & Mastering Guide

## Pre-Mix Preparation
1. **Finish composition first** — don't mix while still writing
2. **Export stems**: File → Export Audio → "All Individual Tracks", normalize ON, return/main effects OFF
3. **Import stems**: turn off "auto warp long samples", set correct BPM, drag all stems in (hold Cmd/Ctrl for individual tracks)
4. **Color code**: group by type (synths, drums, bass, vocals, effects)

## Step 1: Levels (Most Important)
- Set ALL tracks to -∞ (silence)
- Bring in tracks one by one in order of importance:
  1. Kick (start around -12 dB)
  2. Snare/clap
  3. Hi-hats, rides, percussion
  4. Bass
  5. Main synths/instruments
  6. Vocals
  7. Effects, risers, transitions
- Go with your gut — adjust across different sections of the song

## Step 2: Side Chain Compression
- When kick plays, everything else ducks
- Use compressor with sidechain input from kick
- Or use "Duck Buddy" (free Max for Live) — triggered by MIDI, not audio
- Group everything except drums into "not drums" group, apply sidechain there

## Step 3: Reference Tracks
- Pick 2-3 songs you want your mix to sound like
- **Match loudness**: use a loudness meter (LUFS), measure your drop vs reference drops
- Bring reference track volume down to match your integrated LUFS
- A/B compare to notice differences in:
  - Drum punchiness
  - Brightness/high-end
  - Sub bass level
  - Overall balance
- **Measure it**: the mix-check skill bounces the track and runs `tools/mix_check.py` against the
  references (loudness, true peak, band balance, low-end mono), then fixes the biggest gaps

## Step 4: EQ Cleanup
- **Cut low end from tracks that don't need it**: hi-hats, snares, percussion, synths
- Use EQ8 with high-pass filter
- This is one of the most impactful mixing techniques — cleans up the whole mix
- Use steep curve (x4) for precise cuts

## Step 5: Drum Processing
- **Multiband compression on drum group**: glues drums together
  - Match output level on/off to avoid loudness bias
  - Can boost/cut individual frequency bands
- **Saturator on drum group**: Digital Clip setting, drive and output opposite each other
  - Adds crunch without volume increase
  - Reduces peaks → louder master possible later

## Step 6: Sub Bass
- Use Spectrum on master to visualize low end
- Turn off auto-resize, manually zoom into low frequencies
- Compare your sub level against reference tracks
- Ensure consistent sub level across different bass sounds in your track
- Adjust individual bass track volumes to match

## Step 7: Mastering (Master Track via MCP)
The master track uses `track_index = -1` in all MCP tools (`set_track_volume`, `set_track_panning`, `load_instrument_or_effect`, `get_device_parameters`, `batch_set_device_parameters`, etc.).

### Loading effects on master
```
load_instrument_or_effect(track_index=-1, uri="query:AudioFx#Glue%20Compressor")
load_instrument_or_effect(track_index=-1, uri="query:AudioFx#Limiter")
```

### Recommended master chain
1. **Glue Compressor** (device_index 0): gentle bus glue
   - Threshold: ~-10dB (normalized ~0.75)
   - Ratio: 2:1
   - Attack: fast (normalized ~0.33)
   - Release: medium-slow (normalized ~0.67)
   - Makeup: +2dB (normalized ~0.1)
2. **Limiter** (device_index 1): transparent loudness ceiling
   - Ceiling: -0.3dB (normalized ~0.95)
   - Input Gain: slight boost (normalized ~0.55)
   - Auto Release: ON

### Two mastering approaches
- **Clean route**: Limiter — transparent loudness increase
- **Dirty route**: Saturator/clipper — adds character while increasing loudness
- Crank drive as loud as possible WITHOUT audible distortion
- Route reference tracks to "External Out" (bypasses master effects) for fair A/B comparison
- Target similar LUFS as reference tracks

## Export Settings
- Bit depth: 24-bit
- Sample rate: 48kHz or 44.1kHz
- Dither: ON (adds quiet noise to mask digital artifacts)
- Normalize: OFF (for final master)

## Key Principles
- Always compare on/off when adding processing
- Match loudness when comparing (louder always sounds "better")
- Cut before boost with EQ
- Less is more — subtle processing adds up
- Your room/headphones matter — reference tracks help compensate
