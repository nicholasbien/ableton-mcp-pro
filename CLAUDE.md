# Ableton MCP Pro

Control Ableton Live through MCP tools. This project has two parts:

1. **Remote Script** (`AbletonMCP_Remote_Script/__init__.py`) — runs inside Ableton, listens on TCP port 9877
2. **MCP Server** (`MCP_Server/server.py`) — exposes 50+ tools to AI assistants via FastMCP

## Key Conventions

- **Track indexing**: 0+ for regular tracks, `-1` for master, `-2`/`-3` for return A/B
- **Parameter values**: Always normalized 0.0–1.0, regardless of actual range
- **Clip positions**: In beats (4.0 = 1 bar at 4/4)
- **MIDI notes**: pitch 0–127 (C3=48, C4=60), velocity 0–127
- **Arrangement is read-only** — can only populate via `record_arrangement` from session clips

## Music Production Skills

21 skills in `.claude/skills/` activate automatically based on what the user asks for. They cover genres (techno, house, trance, garage, bass music, ambient, synthwave) and production workflows (mixing, mix checks against references, arrangement, swing).

See [SKILL_AUTHORING_GUIDE.md](SKILL_AUTHORING_GUIDE.md) for creating new skills.

## Development

- See [DEVELOPMENT.md](DEVELOPMENT.md) for architecture, threading model, adding commands, and known issues
- See [NEXT_STEPS.md](NEXT_STEPS.md) for roadmap and MCP capability gaps
