"""
Build, arrange and record a techno track in the open Live set, over the remote-script socket.

A worked example (and integration test) of the clip-editing / device / return / drum-pad
tools: every one of them does something musical here, alongside the older tools. Run it on
an empty set (File > New) with the AbletonMCP control surface enabled:

    python tools/demo_song.py [texture.wav]     # ~8 min: 3 min build, 3 min recording, 3 min resample

Structure (130 bpm, F minor, 104 bars): intro 16 | build 8 | groove 16 | break 8 | drop 16 |
breakdown 8 | drop 2 16 | outro 16. Scenes are recorded into the arrangement with
record_arrangement; the audio texture and the drop-2 lead are placed directly in the
arrangement; finally a Resampling track records the master to a WAV, whose path is printed.
"""
import json, socket, sys, time

PORT = 9877
def live(cmd, params=None, timeout=60.0):
    sk = socket.socket(); sk.settimeout(timeout); sk.connect(("localhost", PORT))
    sk.sendall(json.dumps({"type": cmd, "params": params or {}}).encode())
    buf = b""
    while True:
        chunk = sk.recv(1 << 20)
        if not chunk: break
        buf += chunk
        try: r = json.loads(buf); break
        except ValueError: continue
    sk.close()
    if r.get("status") == "error": raise RuntimeError("%s: %s" % (cmd, r.get("message")))
    return r.get("result", r)

def say(label, cmd, params=None, timeout=60.0):
    r = live(cmd, params, timeout); print("%-28s %s: %s" % (cmd, label, json.dumps(r)[:80]), flush=True); return r
def T(name):
    n = int(live("get_session_info")["track_count"])
    for i in range(n):
        if live("get_track_info", {"track_index": i})["name"] == name: return i
    raise KeyError(name)
_pc = {}
def params_of(tr, dev):
    if (tr, dev) not in _pc: _pc[(tr, dev)] = live("get_device_parameters", {"track_index": tr, "device_index": dev}).get("parameters", [])
    return _pc[(tr, dev)]
def pidx(tr, dev, name):
    for i, p in enumerate(params_of(tr, dev)):
        if p.get("name") in (name, name.replace("/", " ")): return p.get("index", i)
    raise KeyError("%s on track %s dev %s" % (name, tr, dev))
def setp(tr, dev, **kv):
    idx = [pidx(tr, dev, k) for k in kv]
    live("batch_set_device_parameters", {"track_index": tr, "device_index": dev, "parameter_indices": idx, "values": list(kv.values())})
def N(p, s, d=0.25, v=100): return {"pitch": p, "start_time": s, "duration": d, "velocity": v, "mute": False}
def notes(tr, slot, ns): live("add_notes_to_clip", {"track_index": tr, "clip_index": slot, "notes": ns})
def clip(tr, slot, length, name): live("create_clip", {"track_index": tr, "clip_index": slot, "length": length}); live("set_clip_name", {"track_index": tr, "clip_index": slot, "name": name})
def copy(tr, src, dst, name): live("duplicate_clip", {"track_index": tr, "clip_index": src, "target_index": dst}); live("set_clip_name", {"track_index": tr, "clip_index": dst, "name": name})
def strip(tr, slot, pitch, t0=0.0, span=-1.0, label=""):
    return say(label or "strip %d" % pitch, "remove_notes", {"track_index": tr, "clip_index": slot, "from_pitch": pitch, "pitch_span": 1, "from_time": t0, "time_span": span})

TEXTURE = sys.argv[1] if len(sys.argv) > 1 else None
BPM = 130.0
live("set_tempo", {"tempo": BPM})

# ---------------------------------------------------------------- tracks
n0 = int(live("get_session_info")["track_count"])
def mk(kind, name, *uris):
    i = live("create_%s_track" % kind, {"index": -1})["index"]; live("set_track_name", {"track_index": i, "name": name})
    for u in uris: live("load_instrument_or_effect", {"track_index": i, "uri": u})
mk("midi", "drums", "query:Drums#FileId_45674", "query:AudioFx#Drum%20Buss")                       # 909 Core Kit
mk("midi", "bass", "query:Synths#Operator", "query:AudioFx#Saturator")
mk("midi", "acid", "query:Synths#Drift", "query:AudioFx#Saturator")
mk("midi", "stabs", "query:Synths#Electric", "query:AudioFx#Auto%20Filter", "query:AudioFx#Chorus-Ensemble")
mk("midi", "pad", "query:Synths#Analog", "query:AudioFx#Auto%20Filter", "query:AudioFx#Reverb")
mk("midi", "lead", "query:Synths#Drift", "query:AudioFx#Auto%20Filter")
mk("audio", "texture", "query:AudioFx#Auto%20Filter")
for i in range(n0 - 1, -1, -1): live("delete_track", {"track_index": i})
DR, BA, AC, ST, PD, LD, TX = [T(n) for n in ("drums", "bass", "acid", "stabs", "pad", "lead", "texture")]
for s in range(int(live("get_arrangement_info")["scene_count"]), 7): live("create_scene", {"index": -1})
for i, n in enumerate(("intro", "build", "groove", "break", "drop", "breakdown", "outro")): live("set_scene_name", {"scene_index": i, "name": n})

# ---------------------------------------------------------------- returns + master
r = say("echo return", "create_return_track"); ECHO = -(r["return_track_count"] + 1)
live("load_instrument_or_effect", {"track_index": ECHO, "uri": "query:AudioFx#Echo"})
say("drop return B (unused stock delay)", "delete_return_track", {"index": 1}); ECHO = -3      # returns: A reverb (-2), echo (-3)
setp(ECHO, 0, **{"Feedback": 0.55, "Dry Wet": 1.0, "LP Freq": 0.6, "HP Freq": 0.3})
live("set_track_volume", {"track_index": ECHO, "volume": 0.72})
for _ in range(8):                                                                          # re-runs: start the master chain clean
    try: live("get_device_parameters", {"track_index": -1, "device_index": 0}); live("delete_device", {"track_index": -1, "device_index": 0})
    except RuntimeError: break
live("load_instrument_or_effect", {"track_index": -1, "uri": "query:AudioFx#Glue%20Compressor"})
live("load_instrument_or_effect", {"track_index": -1, "uri": "query:AudioFx#Limiter"})
say("A/B the master glue: off", "set_device_enabled", {"track_index": -1, "device_index": 0, "enabled": False})
say("... and back on", "set_device_enabled", {"track_index": -1, "device_index": 0, "enabled": True})

# ---------------------------------------------------------------- sound design (techno-drums / techno-bass skills)
setp(DR, 1, **{"Drive": 0.35, "Crunch": 0.15, "Transients": 0.3, "Boom Amt": 0.25, "Boom Freq": 0.42})
setp(BA, 0, **{"Osc-B Level": 0.22, "B Coarse": 2.0 / 48, "Ae Decay": 0.45, "Ae Sustain": 0.6, "Ae Release": 0.3,   # sine sub + a little FM grit
                "Filter Freq": 0.55, "Filter Res": 0.2, "Fe Amount": 0.4, "Fe Decay": 0.4, "Volume": 0.55})
setp(BA, 1, **{"Drive": 0.45})
setp(AC, 0, **{"Osc 2 On": 0.0, "LP Freq": 0.32, "LP Res": 0.62, "LP Mod Amt 2": 0.85, "Env 2 Decay": 0.32,      # Drift as a 303
                "Env 2 Sustain": 0.0, "Env 1 Decay": 0.3, "Env 1 Sustain": 0.4, "Env 1 Release": 0.2,
                "Legato On": 1.0, "Glide Time": 0.25, "Vel > Vol": 0.7, "Volume": 0.5})
setp(AC, 1, **{"Drive": 0.5})
setp(ST, 1, **{"Frequency": 0.5, "Resonance": 0.15}); setp(ST, 2, **{"Dry/Wet": 0.35})
setp(PD, 0, **{"F1 Freq": 0.45, "Volume": 0.55}); setp(PD, 2, **{"Decay Time": 0.8, "Room Size": 0.9, "Dry/Wet": 0.45})
setp(LD, 0, **{"LP Freq": 0.55, "Env 1 Release": 0.35, "Osc 2 On": 1.0, "Osc 2 Detune": 0.56, "Volume": 0.5})
setp(TX, 0, **{"Frequency": 0.45})                                                       # audio track: the filter is device 0

# ---------------------------------------------------------------- drums (slot == scene)
pads = say("kit pad map", "get_drum_pads", {"track_index": DR, "device_index": 0})["pads"]
nm = {}
for p in pads: nm.setdefault(p["name"], p["note"])
K, HH, OH, CP, RM = nm["Bass Drum"], nm["Closed Hi Hat"], nm["Open Hi Hat"], nm["Hand Clap"], nm["Rim Shot"]
RD = nm.get("Ride Cymbal", nm.get("Ride", 51)); CR = nm.get("Crash Cymbal", nm.get("Crash", 49))
print("   pads:", dict(kick=K, hat=HH, ohat=OH, clap=CP, rim=RM, ride=RD, crash=CR))
clip(DR, 2, 4.0, "groove")
g = [N(K, b, 0.25, 120) for b in range(4)]                                                       # metronome kick
g += [N(HH, b + q, 0.15, [96, 44, 66, 40][int(q * 4)]) for b in range(4) for q in (0, .25, .5, .75)]   # 16th hats, sculpted
g += [N(OH, 1.5, 0.25, 70), N(OH, 3.5, 0.25, 74), N(CP, 1.0, 0.25, 92), N(CP, 3.0, 0.25, 96), N(RM, 2.75, 0.2, 58)]
notes(DR, 2, g)
say("groove 1 -> 2 bars", "duplicate_clip_loop", {"track_index": DR, "clip_index": 2})
say("groove 2 -> 4 bars", "duplicate_clip_loop", {"track_index": DR, "clip_index": 2})
say("clap roll into bar 5", "duplicate_region", {"track_index": DR, "clip_index": 2, "region_start": 15.0, "region_length": 1.0, "destination_time": 15.5, "pitch": CP, "transposition_amount": 0})
copy(DR, 2, 0, "intro"); strip(DR, 0, CP, label="intro: no clap"); strip(DR, 0, OH, label="intro: no open hat"); strip(DR, 0, RM, label="intro: no rim")
copy(DR, 0, 1, "build"); notes(DR, 1, [N(RD, b + 0.5, 0.2, 80) for b in range(16)])                # ride on the offbeats
copy(DR, 2, 3, "break"); strip(DR, 3, K, 0.0, 12.0, "break: kick out of bars 1-3")
say("break: rim answer bar 2 -> bar 4", "duplicate_region", {"track_index": DR, "clip_index": 3, "region_start": 4.0, "region_length": 4.0, "destination_time": 12.0, "pitch": RM, "transposition_amount": 0})
copy(DR, 2, 4, "drop"); notes(DR, 4, [N(RD, b + 0.5, 0.2, 88) for b in range(16)] + [N(CR, 0.0, 0.5, 100)])
copy(DR, 2, 5, "breakdown"); strip(DR, 5, K, label="breakdown: no kick"); strip(DR, 5, CP, label="breakdown: no clap"); strip(DR, 5, OH, label="breakdown: no open hat")
copy(DR, 0, 6, "outro")

# ---------------------------------------------------------------- bass: loose 8ths, then quantized; sub sits under the kick
clip(BA, 1, 16.0, "sub")
loose = []
for bar in range(4):
    root = 41 if bar < 3 else 44                                                                  # F1 F1 F1 Ab1
    for e in range(8):
        loose.append(N(root, bar * 4 + e * 0.5 + (0.03 if e % 2 else -0.02), 0.3, 104 if e % 2 == 0 else 78))
notes(BA, 1, loose)
say("snap the bass to 1/16", "quantize_clip", {"track_index": BA, "clip_index": 1, "grid": 5, "strength": 1.0})
for s in (2, 4): copy(BA, 1, s, "sub")

# ---------------------------------------------------------------- acid: 16ths with rests and accents, slides via overlap
clip(AC, 2, 4.0, "acid")
seq = [(41, 120), None, (41, 70), (53, 74), None, (41, 118), None, (44, 72), (41, 70), None, (53, 116), None, (41, 72), (46, 70), None, (44, 118)]
a = [N(p, i * 0.25, 0.28 if v > 100 else 0.22, v) for i, x in enumerate(seq) if x for p, v in [x]]
notes(AC, 2, a)
say("acid 1 -> 2 bars", "duplicate_clip_loop", {"track_index": AC, "clip_index": 2})
say("acid 2 -> 4 bars", "duplicate_clip_loop", {"track_index": AC, "clip_index": 2})
say("acid bar 4 cleared", "remove_notes", {"track_index": AC, "clip_index": 2, "from_pitch": 0, "pitch_span": 128, "from_time": 12.0, "time_span": 4.0})
say("acid bar 4 = bar 1 up a minor third", "duplicate_region", {"track_index": AC, "clip_index": 2, "region_start": 0.0, "region_length": 4.0, "destination_time": 12.0, "pitch": -1, "transposition_amount": 3})
copy(AC, 2, 4, "acid")

# ---------------------------------------------------------------- stabs: Fm7 offbeats, bars 3-4 Bbm7 by transposed copy
clip(ST, 2, 4.0, "stabs")
FM7 = [53, 56, 60, 63]
notes(ST, 2, [N(p, s, 0.22, v) for s, v in ((0.5, 98), (1.5, 76), (2.5, 94), (3.75, 70)) for p in FM7])
say("stabs 1 -> 2 bars", "duplicate_clip_loop", {"track_index": ST, "clip_index": 2})
say("stabs 2 -> 4 bars", "duplicate_clip_loop", {"track_index": ST, "clip_index": 2})
say("stabs bars 3-4 cleared", "remove_notes", {"track_index": ST, "clip_index": 2, "from_pitch": 0, "pitch_span": 128, "from_time": 8.0, "time_span": 8.0})
say("stabs bars 3-4 = bars 1-2 up a fourth (Bbm7)", "duplicate_region", {"track_index": ST, "clip_index": 2, "region_start": 0.0, "region_length": 8.0, "destination_time": 8.0, "pitch": -1, "transposition_amount": 5})
for s in (3, 4): copy(ST, 2, s, "stabs")
live("set_send_level", {"track_index": ST, "send_index": 1, "value": 0.5}); live("set_send_level", {"track_index": ST, "send_index": 0, "value": 0.2})
live("set_send_level", {"track_index": DR, "send_index": 1, "value": 0.08})
say("A/B the stab filter: off", "set_device_enabled", {"track_index": ST, "device_index": 1, "enabled": False})
say("... on", "set_device_enabled", {"track_index": ST, "device_index": 1, "enabled": True})
# a wide double of the stabs: duplicate the track, pan the pair apart, open the double's filter a little
say("stabs -> stabs (wide)", "duplicate_track", {"track_index": ST})
ST, SW = T("stabs"), T("stabs") + 1
live("set_track_name", {"track_index": SW, "name": "stabs (wide)"})
live("set_track_panning", {"track_index": ST, "panning": 0.3}); live("set_track_panning", {"track_index": SW, "panning": 0.72})
setp(SW, 1, **{"Frequency": 0.62}); setp(SW, 2, **{"Dry/Wet": 0.5}); live("set_track_volume", {"track_index": SW, "volume": 0.5})
DR, BA, AC, PD, LD, TX = [T(n) for n in ("drums", "bass", "acid", "pad", "lead", "texture")]

# ---------------------------------------------------------------- pad: Fm9 held, filter opening over the clip (clip envelope)
for s in (3, 5):
    clip(PD, s, 32.0, "pad"); notes(PD, s, [N(p, 0.0, 31.5, 70) for p in (41, 48, 53, 56, 60, 67)])
    fi = pidx(PD, 1, "Frequency")
    live("set_clip_envelope", {"track_index": PD, "clip_index": s, "device_index": 1, "parameter_index": fi,
                               "points": [{"time": 0.0, "value": 0.12}, {"time": 24.0, "value": 0.7}, {"time": 32.0, "value": 0.95}]})
print("   pad clips with a 32-beat filter sweep", flush=True)
live("set_send_level", {"track_index": PD, "send_index": 1, "value": 0.3})

# ---------------------------------------------------------------- mix
for tr, v in ((DR, 0.85), (BA, 0.8), (AC, 0.6), (ST, 0.55), (PD, 0.45), (LD, 0.6), (TX, 0.5)): live("set_track_volume", {"track_index": tr, "volume": v})

# ---------------------------------------------------------------- scenes -> arrangement (real time)
sections = [(0, 16), (1, 8), (2, 16), (3, 8), (4, 16), (5, 8), (4, 16), (6, 16)]
print("recording %d bars of scenes into the arrangement (~%d s)..." % (sum(b for _, b in sections), sum(b for _, b in sections) * 4 * 60 / BPM), flush=True)
say("scenes -> arrangement", "record_arrangement", {"sections": [{"scene_index": s, "bars": b} for s, b in sections], "start_time": 0.0}, timeout=400)
say("all clips stop", "stop_all_clips", {"quantized": False})
live("set_back_to_arranger")

# ---------------------------------------------------------------- arrangement-only material
bar = lambda b: (b - 1) * 4.0
# drop 2 lead (bars 73-88): F minor pentatonic riff, 4-bar phrase x4, placed straight into the arrangement
riff = [(77, 0, .5), (80, .5, .5), (84, 1, 1), (80, 2.5, .5), (77, 3, 1), (75, 4.5, .5), (77, 5, 1.5), (72, 7, 1),
        (77, 8, .5), (80, 8.5, .5), (84, 9, 1), (87, 10.5, .5), (84, 11, 1), (80, 12.5, .5), (77, 13, 2), (75, 15.5, .5)]
lead = [N(p, s + rep * 16, d, 92) for rep in range(4) for p, s, d in riff]
say("lead placed in drop 2", "create_arrangement_midi_clip", {"track_index": LD, "time": bar(73), "length": 64.0, "notes": lead})
live("set_send_level", {"track_index": LD, "send_index": 1, "value": 0.45})
# audio texture through the breakdown and the first half of drop 2, pulled from A minor down to F minor
if TEXTURE:
    for k, b in enumerate((57, 61, 65, 69)):
        live("create_arrangement_audio_clip", {"track_index": TX, "file_path": TEXTURE, "time": bar(b)})
        A = {"track_index": TX, "clip_index": 0, "arrangement_clip_index": k}
        live("set_clip_warping", dict(A, warping=True)); live("set_clip_warp_mode", dict(A, warp_mode=4))
        live("set_clip_pitch", dict(A, coarse=-4, fine=0)); live("set_clip_gain", dict(A, gain=0.28 if k < 2 else 0.36))
    print("   texture: 4 warped clips, -4 st, Complex", flush=True)
# tidy: nothing should sit past the outro
info = live("get_arrangement_info"); end_beat = bar(105)
for tr in range(int(live("get_session_info")["track_count"])):
    cl = live("get_arrangement_clips", {"track_index": tr})["clips"]
    for i in range(len(cl) - 1, -1, -1):
        if cl[i]["start_time"] >= end_beat: say("trim stray clip", "delete_arrangement_clip", {"track_index": tr, "arrangement_clip_index": i})

# ---------------------------------------------------------------- record the master with a Resampling track
REC = live("create_audio_track", {"index": -1})["index"]; live("set_track_name", {"track_index": REC, "name": "master rec"})
live("set_track_input_routing", {"track_index": REC, "routing_type_name": "Resampling"})
live("set_track_monitoring", {"track_index": REC, "state": 2}); live("set_track_arm", {"track_index": REC, "arm": True})
live("set_song_time", {"time": 0.0}); live("set_record_mode", {"on": True}); live("play_arrangement", {"time": 0.0})
time.sleep(2.0)
pos = live("get_arrangement_info")["current_song_time"]
if pos > 8.0: live("set_song_time", {"time": 0.0})                                # play started from the insert marker: relocate
secs = (end_beat + 8) * 60.0 / BPM
print("resampling the master: %.0f s..." % secs, flush=True); time.sleep(secs)
live("stop_playback"); live("set_record_mode", {"on": False}); live("set_track_arm", {"track_index": REC, "arm": False})
rec = live("get_arrangement_clips", {"track_index": REC})["clips"]
live("set_song_time", {"time": 0.0})
print("RECORDED:", json.dumps([(c.get("file_path"), c.get("start_time"), c.get("length")) for c in rec]))
print(json.dumps({"song_bars": live("get_arrangement_info")["song_length"] / 4, "tempo": BPM}))
