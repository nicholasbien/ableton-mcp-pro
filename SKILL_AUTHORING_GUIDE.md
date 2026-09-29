# Skill Authoring Guide

Best practices for creating and maintaining music production skills for Ableton MCP.

## What Makes a Good Skill

### The Bar: "Excellent"
An excellent skill lets Claude execute a complete production workflow — from empty Ableton session to a playable result — using only MCP tool calls. Every line should either be a concrete action or context that directly informs one.

### Quality Checklist
- [ ] Specific parameter values (not "add some reverb" — "Reverb: decay 3.5s, pre-delay 20ms, diffusion 80%")
- [ ] Actionable via MCP (no manual drag-and-drop, no GUI-only operations)
- [ ] Build order at the end (numbered steps matching MCP tool sequence)
- [ ] At least one ASCII pattern diagram for drum/rhythm skills
- [ ] Grounded in research (multiple sources including blog posts and videos, not just AI knowledge)
- [ ] Synthesized from 2+ sources
- [ ] 80-140 lines (shorter = incomplete, longer = bloated)

## File Structure

```
.claude/skills/<skill-name>/SKILL.md
```

### YAML Frontmatter (required)
```yaml
---
name: skill-name
description: One sentence. Start with "Create..." Use when the user asks for X, Y, Z, or W.
---
```

The `description` field controls when Claude activates the skill. Include:
- The primary thing it creates
- 4-6 trigger phrases covering common ways users might ask for it
- No artist names unless truly genre-defining

### Standard Sections

1. **Quick Reference** — Tempo, key, time signature, feel (2-4 bullets)
2. **Sound Design** — Specific synth patches with parameter values
3. **Patterns** — ASCII diagrams, MIDI note values, velocity ranges
4. **Processing** — Effects chain with specific settings
5. **Mixing** — Levels, sidechain, EQ, mono/stereo
6. **Build Order** — Numbered steps matching the workflow

Not every skill needs all sections. A bass skill doesn't need pattern diagrams. A drums skill doesn't need sound design depth. Match the structure to the content.

## MCP Compatibility

### Always check: can Claude actually do this?

**Fully supported operations:**
- Create MIDI tracks, clips, add notes
- Load Operator, Wavetable, Analog, Simpler, Drum Rack
- Load any effect (EQ8, Compressor, Reverb, Saturator, Auto Filter, etc.)
- Set device parameters by index (normalized 0.0-1.0)
- Set track volume, panning, send levels
- Write clip automation envelopes
- Set tempo, time signature

**NOT supported (avoid in skills or note as manual steps):**
- Creating Instrument/Audio Effect Racks with chains
- Loading MIDI effects (Chord, Scale, Arpeggiator)
- Applying groove templates from Groove Pool
- Slicing audio to MIDI
- Macro mapping
- Grouping tracks
- Freezing/flattening

If a skill requires unsupported operations for its core workflow, either find a workaround or don't create the skill. A skill that can't be executed is worse than no skill.

## Writing Parameter Values

### Be specific enough for `set_device_parameter`
MCP sets parameters by index and normalized value (0.0-1.0). Write values that translate:

**Good:** "Filter cutoff: 45% (low-pass 24dB)"
**Bad:** "Open the filter a bit"

**Good:** "Attack: 5ms, Decay: 200ms, Sustain: 70%, Release: 50ms"
**Bad:** "Short punchy envelope"

### Operator parameters to know
- Oscillator waveform is set via device parameter (not always obvious which index)
- FM amount = modulator oscillator's level
- Algorithm/routing = a single parameter with discrete values
- Always specify: waveform, level (dB), coarse tune, fine tune for each active oscillator

### When exact values aren't possible
Some settings depend on context (e.g., "sidechain release depends on tempo"). Give a formula or range:
- "Release: ~120ms at 140 BPM (one 16th note = 107ms, leave headroom)"
- "Cutoff: 30-50% depending on how bright you want the attack"

## Pattern Diagrams

### ASCII Format
```
Beat:  1 . . . 2 . . . 3 . . . 4 . . . | 1 . . . 2 . . . 3 . . . 4 . . .
Kick:  X . . . X . . . X . . . X . . . | X . . . X . . . X . . . X . . .
Snare: . . . . X . . . . . . . X . . . | . . . . X . . . . . . . X . . .
Hat:   X . X . X . X . X . X . X . X . | X . X . X . X . X . X . X . X .
Ghost: . . . g . . . . . g . . . g . . | . g . . . . . g . . . g . . g .
```

- Use `X` for main hits, `g` for ghost notes
- 16th note resolution (4 positions per beat)
- 2 bars separated by `|`
- Include velocity guidance in text ("Ghost: velocity 40-60, main hits: 100-127")

### When to include patterns
- Drum skills: always (2-3 patterns minimum)
- Bass skills: include if the rhythm is important (e.g., trance bass types, walking bass)
- Chord/pad skills: usually not needed

## Research Process

### Minimum: 2 distinct sources per skill

Use a mix of video tutorials and blog posts to ground each skill in real production knowledge:

- Search for specific techniques, not generic overviews
- Look for concrete parameter values and workflow steps
- Different creators have different approaches — that's the point
- Synthesize insights across sources rather than copying from any single one

### What to extract from sources
- Specific parameter values (filter cutoff at X Hz, decay at Y ms)
- Sound selection tips (why this waveform, why this sample type)
- Pattern placement insights (why the kick goes HERE, not there)
- Processing order and reasoning

### What NOT to copy
- Direct quotes from tutorials
- Artist name attributions (unless truly genre-defining)
- Exact phrases that would identify the source
- Subjective opinions presented as rules

## Maintenance

### When to update a skill
- New MCP capabilities unlock previously-blocked features
- A technique turns out to be wrong in practice (test against Ableton)
- A user reports that a skill produces bad results
- New research reveals better approaches

### When to remove a skill
- Core workflow depends on MCP features we don't have
- Overlaps too heavily with another skill
- The genre/technique is too niche to be useful
- Can't produce a usable result even with workarounds
