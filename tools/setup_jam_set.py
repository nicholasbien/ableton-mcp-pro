"""
Set up the open Live set for jamming with fluidclaude (`--engine midi` + `listen`):

    you          your keyboard in, no instrument, MIDI To -> IAC Bus 3  (fluidclaude listens here)
    you (sound)  your instrument, MIDI From -> "you", Monitor In      (Live sounds your playing)
    reply        the model's instrument, MIDI From -> IAC Bus 2 / Ch. 5, Monitor In
    <loops>      one track per fluidclaude loop channel you name, MIDI From -> IAC Bus 2 / Ch. N

then prints the fluidclaude commands. A MIDI track with an instrument outputs audio, so the
play-in track has no instrument (that is why "you" is split in two). Tick Sync on IAC Bus 1
in Live's MIDI preferences (Output) so fluidclaude can follow Live's clock.

    python tools/setup_jam_set.py                                  # you + reply
    python tools/setup_jam_set.py --loops bass:1,kick:9,stabs:2    # plus tracks for fluidclaude loops
    python tools/setup_jam_set.py --keyboard "Your Keyboard"       # pick the keyboard input by name
"""
import argparse, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from live_client import live, track_by_name, LiveError

ap = argparse.ArgumentParser()
ap.add_argument("--keyboard", default=None, help="input routing for 'you' (substring; default: first non-IAC hardware input)")
ap.add_argument("--you-instrument", default="query:Synths#Electric")
ap.add_argument("--reply-instrument", default="query:Synths#Drift")
ap.add_argument("--in-bus", default="IAC Driver (Bus 3)", help="bus 'you' sends to (fluidclaude listens on it)")
ap.add_argument("--out-bus", default="IAC Driver (Bus 2)", help="bus fluidclaude's midi engine plays on")
ap.add_argument("--reply-channel", type=int, default=5, help="MIDI channel (1-16) the reply loop is pinned to")
ap.add_argument("--loops", default="", help="NAME:CH,... extra tracks for fluidclaude loops (CH 1-16 as fluidclaude prints them, +1)")
args = ap.parse_args()

def make(name, instrument=None):
    i = track_by_name(name)
    if i is None:
        i = live("create_midi_track", {"index": -1})["index"]
        live("set_track_name", {"track_index": i, "name": name})
    if instrument and not live("get_track_info", {"track_index": i})["devices"]:
        live("load_instrument_or_effect", {"track_index": i, "uri": instrument})
    live("set_track_arm", {"track_index": i, "arm": False})
    return i

def route_in(i, needle, channel=None):
    avail = [t["display_name"] for t in live("get_track_routing", {"track_index": i})["available_input_routing_types"]]
    name = next((n for n in avail if needle.lower() in n.lower()), None)
    if not name:
        return f"MANUAL: track {i}: set MIDI From to something matching {needle!r} (available: {', '.join(avail)})"
    params = {"track_index": i, "routing_type_name": name}
    if channel: params["channel_name"] = channel
    r = live("set_track_input_routing", params)
    return f"{name} / {r.get('input_routing_channel')}"

def route_out(i, needle):
    avail = [t["display_name"] for t in live("get_track_routing", {"track_index": i})["available_output_routing_types"]]
    name = next((n for n in avail if needle.lower() in n.lower()), None)
    if not name:
        return f"MANUAL: track {i}: set MIDI To to something matching {needle!r} (available: {', '.join(avail)})"
    live("set_track_output_routing", {"track_index": i, "routing_type_name": name}); return name

notes = []
you = make("you")
kb = args.keyboard
if kb is None:
    avail = [t["display_name"] for t in live("get_track_routing", {"track_index": you})["available_input_routing_types"]]
    hw = [n for n in avail if "IAC" not in n and n not in ("All Ins", "Computer Keyboard", "No Input") and track_by_name(n) is None]
    # never "All Ins": it includes the IAC bus fluidclaude plays on, so the loops would come back
    # in as "calls" (feedback). No hardware keyboard -> Live's computer keyboard (press M in Live).
    kb = hw[0] if hw else "Computer Keyboard"
notes.append(f"you: MIDI From {route_in(you, kb)}, MIDI To {route_out(you, args.in_bus)}")
live("set_track_monitoring", {"track_index": you, "state": 0})
live("set_track_arm", {"track_index": you, "arm": True})          # the computer keyboard only reaches an armed track
snd = make("you (sound)", args.you_instrument)
notes.append(f"you (sound): MIDI From {route_in(snd, 'you')}, Monitor In")
live("set_track_monitoring", {"track_index": snd, "state": 0})
reply = make("reply", args.reply_instrument)
notes.append(f"reply: MIDI From {route_in(reply, args.out_bus, 'Ch. %d' % args.reply_channel)}, Monitor In")
live("set_track_monitoring", {"track_index": reply, "state": 0})
loop_args = []
for spec in [x for x in args.loops.split(",") if x]:
    name, _, ch = spec.partition(":")
    i = make(name, args.reply_instrument)
    notes.append(f"{name}: MIDI From {route_in(i, args.out_bus, 'Ch. %s' % ch)}, Monitor In")
    live("set_track_monitoring", {"track_index": i, "state": 0})
    loop_args.append(f"{name} ch={int(ch) - 1}")
print("\n".join(notes))
print("\nfluidclaude:")
print(f'  uv run fluidclaude --engine midi --midi-port "{args.out_bus.replace(" (", " ").rstrip(")")}" start')
print(f'  uv run fluidclaude send "listen \'{args.in_bus.replace(" (", " ").rstrip(")")}\' clock=\'IAC Driver Bus 1\' thru=off answer=reply bars=4 ch={args.reply_channel - 1}"')
if loop_args:
    print("  loops pinned to their tracks: " + "; ".join(f"loop {a} ..." for a in loop_args))
print("Live: Preferences > Link/Tempo/MIDI > Output 'IAC Driver (Bus 1)' > Sync on, so fluidclaude follows the clock.")
