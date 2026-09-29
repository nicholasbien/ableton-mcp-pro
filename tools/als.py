"""
Read and edit Ableton Live Set files (.als = gzipped XML) offline, for the things the Live Object
Model can't do (relink samples, inspect a set without opening it) or when Live isn't running.
Standard library only; understands the Live 10, 11 and 12 layouts.

    python tools/als.py summary SET.als [--json]
    python tools/als.py samples SET.als [--missing] [--json]
    python tools/als.py set-tempo SET.als 124 -o OUT.als
    python tools/als.py rename-track SET.als "2-Audio" "Vox" -o OUT.als     # index or name
    python tools/als.py set-color SET.als 0 12 -o OUT.als
    python tools/als.py relink SET.als /Users/old/Samples /Volumes/ext/Samples -o OUT.als

    import sys; sys.path.insert(0, "path/to/ableton-mcp-pro/tools")
    import als
    tree = als.load("song.als")
    als.summary(tree)["tempo"]
    als.set_tempo(tree, 128); als.save(tree, "song-128.als")

Edits only ever write to the path you give (-o is required on the CLI; it may equal the input).
save() re-serializes byte-for-byte the way Live writes (checked against ~450 real sets), writes
to a temp file and renames it into place. Close the set in Live before overwriting it.

Track indices follow the MCP server: 0+ regular tracks, -1 main/master, -2/-3/... returns A/B/...
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

TRACK_TYPES = {"MidiTrack": "midi", "AudioTrack": "audio", "GroupTrack": "group",
               "ReturnTrack": "return"}
# Plugin devices keep their display name inside PluginDesc, not in UserName.
PLUGIN_NAME_PATHS = ("PluginDesc/*/PlugName", "PluginDesc/*/Name")


class AlsError(ValueError):
    pass


# --- load / save ----------------------------------------------------------------------------

def load(path: str) -> ET.ElementTree:
    """Parse a .als (gzipped or plain XML). Remembers the source path, the bytes around the root
    element and Live's attribute-quoting style so save() can write the file back identically."""
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    start = raw.find(b"<Ableton")
    end = raw.rfind(b"</Ableton>")
    if start < 0 or end < 0:
        raise AlsError(f"{path}: not an Ableton Live Set (no <Ableton> root)")
    tree = ET.ElementTree(ET.fromstring(raw))
    tree.als_path = os.path.abspath(path)
    tree.als_head = raw[:start]                         # XML declaration + newline
    tree.als_tail = raw[end + len(b"</Ableton>"):]      # trailing newline
    # Live 10 escapes " inside attributes as &quot;, Live 11/12 switch to single quotes.
    if b"&quot;" in raw:
        tree.als_apos = False
    elif re.search(rb"=\'", raw):
        tree.als_apos = True
    else:
        tree.als_apos = _major(tree) >= 11
    return tree


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _attr(v: str, apos: bool) -> str:
    s = _esc(v).replace("\n", "&#x0A;").replace("\r", "&#x0D;").replace("\t", "&#x09;")
    if '"' in s:
        if apos and "'" not in s:
            return "'" + s + "'"
        s = s.replace('"', "&quot;")
    return '"' + s + '"'


def _serialize(e: ET.Element, out: list, apos: bool) -> None:
    out.append("<" + e.tag)
    for k, v in e.attrib.items():
        out.append(" " + k + "=" + _attr(v, apos))
    if len(e) or e.text:
        out.append(">")
        if e.text:
            out.append(_esc(e.text))
        for c in e:
            _serialize(c, out, apos)
        out.append("</" + e.tag + ">")
    else:
        out.append(" />")                               # Live's empty-element style
    if e.tail:
        out.append(_esc(e.tail))


def to_bytes(tree: ET.ElementTree) -> bytes:
    """The uncompressed XML, formatted the way Live writes it."""
    out: list = []
    _serialize(tree.getroot(), out, getattr(tree, "als_apos", True))
    head = getattr(tree, "als_head", b'<?xml version="1.0" encoding="UTF-8"?>\n')
    tail = getattr(tree, "als_tail", b"\n")
    return head + "".join(out).encode("utf-8") + tail


def save(tree: ET.ElementTree, path: str) -> None:
    """Gzip and write atomically (temp file in the same directory, then rename)."""
    data = gzip.compress(to_bytes(tree), compresslevel=6, mtime=0)
    path = os.path.abspath(path)
    fd, tmp = tempfile.mkstemp(prefix=".als-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# --- navigation -----------------------------------------------------------------------------

def _liveset(tree: ET.ElementTree) -> ET.Element:
    ls = tree.getroot().find("LiveSet")
    if ls is None:
        raise AlsError("no <LiveSet> element")
    return ls


def _major(tree: ET.ElementTree) -> int:
    m = re.search(r"(\d+)\.", tree.getroot().get("Creator", ""))
    return int(m.group(1)) if m else 0


def _val(e: ET.Element | None, path: str, default=None):
    """Value attribute of the child at `path` (or of `e` itself when path is '')."""
    if e is None:
        return default
    n = e.find(path) if path else e
    return default if n is None else n.get("Value", default)


def _num(s):
    f = float(s)
    return int(f) if f.is_integer() else f


def _fmt(x: float) -> str:
    """Numbers the way Live writes them: 120, 127.5."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def _main_track(ls: ET.Element) -> ET.Element:
    # Live 12 renamed MasterTrack to MainTrack.
    m = ls.find("MainTrack")
    if m is None:
        m = ls.find("MasterTrack")
    if m is None:
        raise AlsError("no MainTrack/MasterTrack")
    return m


def _all_tracks(ls: ET.Element) -> list[ET.Element]:
    return [t for t in ls.find("Tracks") if t.tag in TRACK_TYPES]


def _regular_tracks(ls):
    return [t for t in _all_tracks(ls) if t.tag != "ReturnTrack"]


def _return_tracks(ls):
    return [t for t in _all_tracks(ls) if t.tag == "ReturnTrack"]


def _track_name(t: ET.Element) -> str:
    return _val(t, "Name/UserName") or _val(t, "Name/EffectiveName", "")


def _color(t: ET.Element):
    c = t.find("Color")                                 # Live 11+
    if c is None:
        c = t.find("ColorIndex")                        # Live 10
    return None if c is None else int(c.get("Value"))


def _devices(t: ET.Element) -> list[dict]:
    devs = t.find("DeviceChain/DeviceChain/Devices")
    out = []
    for d in (devs if devs is not None else []):
        name = _val(d, "UserName") or ""
        if not name:
            for p in PLUGIN_NAME_PATHS:
                name = _val(d, p) or ""
                if name:
                    break
        out.append({"type": d.tag, "name": name})
    return out


def _clip_counts(t: ET.Element) -> tuple[int, int]:
    seq = t.find("DeviceChain/MainSequencer")
    if seq is None:                                     # group/return tracks hold no clips
        return 0, 0
    session = len(seq.findall("ClipSlotList/ClipSlot/ClipSlot/Value/*"))
    # MIDI clips sit under ClipTimeable, audio clips under Sample (take lanes not counted)
    arrangement = len(seq.findall("*/ArrangerAutomation/Events/*"))
    return session, arrangement


def _tempo_node(ls: ET.Element) -> ET.Element:
    t = _main_track(ls).find("DeviceChain/Mixer/Tempo")
    if t is None:
        raise AlsError("no Tempo in the main track mixer")
    return t


def _envelope_events(ls: ET.Element, param: ET.Element) -> list[ET.Element]:
    """Arrangement automation events of a main-track parameter ([] if none)."""
    target = param.find("AutomationTarget")
    if target is None:
        return []
    tid = target.get("Id")
    for env in _main_track(ls).findall("AutomationEnvelopes/Envelopes/AutomationEnvelope"):
        if _val(env, "EnvelopeTarget/PointeeId") == tid:
            return env.findall("Automation/Events/*")
    return []


def _is_automated(ls: ET.Element, param: ET.Element) -> bool:
    # Live saves a one-point envelope (at time -63072000) for the tempo of nearly every set;
    # that's a constant, not automation.
    return len({e.get("Value") for e in _envelope_events(ls, param)}) > 1


def decode_time_signature(v: int) -> tuple[int, int]:
    """Live stores numerator-1 + 99 * log2(denominator): 201 = 4/4, 302 = 6/8."""
    return v % 99 + 1, 2 ** (v // 99)


def find_track(tree: ET.ElementTree, which) -> ET.Element:
    """A track by index (0+ regular, -1 main, -2/-3... returns) or by exact name
    (UserName or EffectiveName; falls back to a unique case-insensitive match)."""
    ls = _liveset(tree)
    if isinstance(which, str) and re.fullmatch(r"-?\d+", which.strip()):
        which = int(which)
    if isinstance(which, int):
        regular = _regular_tracks(ls)
        if which >= 0:
            if which >= len(regular):
                raise AlsError(f"track index {which} out of range (set has {len(regular)} tracks)")
            return regular[which]
        if which == -1:
            return _main_track(ls)
        returns = _return_tracks(ls)
        if -which - 2 >= len(returns):
            raise AlsError(f"return index {which} out of range ({len(returns)} returns)")
        return returns[-which - 2]
    tracks = _all_tracks(ls)
    names = lambda t: {_val(t, "Name/UserName"), _val(t, "Name/EffectiveName")} - {None, ""}
    hits = [t for t in tracks if which in names(t)]
    if not hits:
        hits = [t for t in tracks if which.lower() in {n.lower() for n in names(t)}]
    if len(hits) != 1:
        raise AlsError(f"{'no' if not hits else len(hits)} tracks named {which!r}")
    return hits[0]


# --- summary --------------------------------------------------------------------------------

def summary(tree: ET.ElementTree) -> dict:
    root, ls = tree.getroot(), _liveset(tree)
    main = _main_track(ls)
    tempo = _tempo_node(ls)
    ts = _val(main, "DeviceChain/Mixer/TimeSignature/Manual")
    num, den = decode_time_signature(int(ts)) if ts is not None else (None, None)

    def track_info(t):
        session, arrangement = _clip_counts(t)
        return {"type": TRACK_TYPES[t.tag], "name": _track_name(t),
                "effective_name": _val(t, "Name/EffectiveName", ""), "color": _color(t),
                "group_id": int(_val(t, "TrackGroupId", -1)), "devices": _devices(t),
                "session_clips": session, "arrangement_clips": arrangement}

    tracks = [track_info(t) for t in _regular_tracks(ls)]
    for i, t in enumerate(tracks):
        t["index"] = i
    returns = []
    for i, t in enumerate(_return_tracks(ls)):
        info = track_info(t)
        del info["session_clips"], info["arrangement_clips"], info["group_id"]
        returns.append({"index": -2 - i, **info})

    if ls.find("Scenes") is not None:                   # Live 11+
        scenes = [_val(s, "Name", "") for s in ls.findall("Scenes/Scene")]
    else:                                               # Live 10: <SceneNames><Scene Value=..>
        scenes = [s.get("Value", "") for s in ls.findall("SceneNames/Scene")]
    locators = [{"name": _val(l, "Name", ""), "time": _num(_val(l, "Time", 0))}
                for l in ls.findall("Locators/Locators/Locator")]

    return {
        "creator": root.get("Creator"), "minor_version": root.get("MinorVersion"),
        "tempo": _num(_val(tempo, "Manual")), "tempo_automated": _is_automated(ls, tempo),
        "time_signature": f"{num}/{den}" if num else None,
        "tracks": tracks, "returns": returns,
        "main": {"name": _track_name(main), "devices": _devices(main)},
        "scenes": scenes, "locators": locators,
    }


def format_summary(s: dict) -> str:
    lines = [f"{s['creator']} (schema {s['minor_version']})",
             f"tempo {s['tempo']}{' (automated)' if s['tempo_automated'] else ''}  "
             f"time signature {s['time_signature']}", ""]

    def devs(d):
        return ", ".join(x["type"] + (f" '{x['name']}'" if x["name"] else "") for x in d) or "-"

    for t in s["tracks"] + s["returns"]:
        clips = (f"  session {t['session_clips']}, arrangement {t['arrangement_clips']}"
                 if "session_clips" in t else "")
        lines.append(f"{t['index']:>3}  {t['type']:<6} {t['name']!r:<32} color {t['color']}{clips}")
        lines.append(f"       devices: {devs(t['devices'])}")
    lines.append(f"main   devices: {devs(s['main']['devices'])}")
    named = [f"{i}:{n}" for i, n in enumerate(s["scenes"]) if n.strip()]
    lines.append(f"scenes: {len(s['scenes'])}" + (f"  ({', '.join(named)})" if named else ""))
    if s["locators"]:
        lines.append("locators: " + ", ".join(f"{l['name']!r}@{l['time']}" for l in s["locators"]))
    return "\n".join(lines)


# --- edits ----------------------------------------------------------------------------------

def set_tempo(tree: ET.ElementTree, bpm: float) -> None:
    """Set the song tempo: the Manual value plus the constant one-point arrangement envelope Live
    keeps next to it (the arrangement reads that, not Manual). Real tempo automation (an envelope
    with varying values) is left alone; summary()['tempo_automated'] tells you if there is some."""
    if not 20 <= bpm <= 999:
        raise AlsError("tempo must be between 20 and 999 BPM")
    ls = _liveset(tree)
    tempo = _tempo_node(ls)
    tempo.find("Manual").set("Value", _fmt(bpm))
    if not _is_automated(ls, tempo):
        for e in _envelope_events(ls, tempo):
            e.set("Value", _fmt(bpm))


def rename_track(tree: ET.ElementTree, index_or_name, new_name: str) -> None:
    t = find_track(tree, index_or_name)
    # Live keeps both: UserName is what you typed, EffectiveName what's displayed.
    for tag in ("UserName", "EffectiveName"):
        n = t.find("Name/" + tag)
        if n is not None:
            n.set("Value", new_name)


def set_track_color(tree: ET.ElementTree, index_or_name, color_index: int) -> None:
    """Set a track's palette color (Live's 70-color palette: 0-69)."""
    if not 0 <= int(color_index) <= 69:
        raise AlsError("color index must be 0-69")
    t = find_track(tree, index_or_name)
    c = t.find("Color")
    if c is None:
        c = t.find("ColorIndex")
    if c is None:
        raise AlsError("track has no Color/ColorIndex element")
    c.set("Value", str(int(color_index)))


def _project_root(set_dir: str) -> str:
    d = set_dir
    while True:
        if os.path.isdir(os.path.join(d, "Ableton Project Info")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return set_dir
        d = parent


def _join_dirs(dirs: list[str], name: str) -> str:
    parts = [d for d in dirs] + [name]
    path = "/".join(parts)
    return path if parts and parts[0].endswith(":") else "/" + path    # Windows drive letter


def _fileref_paths(fr: ET.Element) -> tuple[str, str]:
    """(absolute path, path relative to set/project) for one FileRef, either layout."""
    path_el = fr.find("Path")
    if path_el is not None:                             # Live 11+
        return path_el.get("Value", ""), _val(fr, "RelativePath", "") or ""
    name = _val(fr, "Name", "")                         # Live 10: dirs as child elements
    hint = [e.get("Dir", "") for e in fr.findall("SearchHint/PathHint/RelativePathElement")]
    rel = [e.get("Dir", "") or ".." for e in fr.findall("RelativePath/RelativePathElement")]
    return (_join_dirs(hint, name) if hint else ""), "/".join(rel + [name])


def _sample_refs(tree: ET.ElementTree) -> list[ET.Element]:
    return [fr for sr in _liveset(tree).iter("SampleRef")
            for fr in sr.findall("FileRef")]


def list_samples(tree: ET.ElementTree, set_path: str | None = None) -> list[dict]:
    """Every sample the set references (deduplicated), with whether it exists on disk. A sample
    whose absolute path is stale still counts as found if its set/project-relative path resolves,
    which is how Live finds it after a project folder moves."""
    set_path = set_path or getattr(tree, "als_path", None)
    set_dir = os.path.dirname(set_path) if set_path else None
    out: dict[str, dict] = {}
    for fr in _sample_refs(tree):
        path, rel = _fileref_paths(fr)
        rtype = _val(fr, "RelativePathType")
        key = path or rel
        if key in out:
            out[key]["refs"] += 1
            continue
        found = path if path and os.path.exists(path) else None
        if not found and set_dir and rel and rtype in ("1", "3"):
            base = set_dir if rtype == "1" else _project_root(set_dir)
            cand = os.path.normpath(os.path.join(base, rel))
            found = cand if os.path.exists(cand) else None
        out[key] = {"path": path, "relative_path": rel, "relative_type": rtype,
                    "exists": found is not None, "found_at": found, "refs": 1}
    return list(out.values())


def relink_samples(tree: ET.ElementTree, old_prefix: str, new_prefix: str) -> int:
    """Rewrite the absolute path of every sample reference starting with old_prefix. Returns
    the number of references changed. Include the trailing slash to match whole folders."""
    changed = 0
    for fr in _sample_refs(tree):
        path, _ = _fileref_paths(fr)
        if not path or not path.startswith(old_prefix):
            continue
        new = new_prefix + path[len(old_prefix):]
        path_el = fr.find("Path")
        if path_el is not None:
            path_el.set("Value", new)
        else:
            # Live 10: rebuild SearchHint/PathHint dirs + Name. The binary alias in <Data> is left
            # alone; when it no longer resolves Live falls back to the hint.
            hint = fr.find("SearchHint/PathHint")
            if hint is None:
                continue
            dirs = [d for d in new.split("/") if d]
            name = dirs.pop()
            first_id = int(hint[0].get("Id", 0)) if len(hint) else 0
            indent = hint.text or ""
            last_tail = hint[-1].tail if len(hint) else ""
            for e in list(hint):
                hint.remove(e)
            for i, d in enumerate(dirs):
                e = ET.SubElement(hint, "RelativePathElement", {"Id": str(first_id + i), "Dir": d})
                e.tail = indent
            if len(hint):
                hint[-1].tail = last_tail
            fr.find("Name").set("Value", name)
        changed += 1
    return changed


# --- CLI ------------------------------------------------------------------------------------

def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(),
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("summary", help="tempo, tracks, devices, clips, scenes, locators")
    p.add_argument("set")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("samples", help="list referenced sample files")
    p.add_argument("set")
    p.add_argument("--missing", action="store_true", help="only samples not found on disk")
    p.add_argument("--json", action="store_true")

    def edit(name, help, *args):
        p = sub.add_parser(name, help=help)
        p.add_argument("set")
        for a in args:
            p.add_argument(a)
        p.add_argument("-o", "--output", required=True, help="output .als (may equal the input)")

    edit("set-tempo", "set the song tempo", "bpm")
    edit("rename-track", "rename a track (index or current name)", "track", "new_name")
    edit("set-color", "set a track's color (0-69)", "track", "color")
    edit("relink", "rewrite sample paths starting with OLD to start with NEW", "old", "new")

    a = ap.parse_args(argv)
    try:
        tree = load(a.set)
        if a.cmd == "summary":
            s = summary(tree)
            print(json.dumps(s, indent=2) if a.json else format_summary(s))
            return 0
        if a.cmd == "samples":
            rows = [r for r in list_samples(tree) if not (a.missing and r["exists"])]
            if a.json:
                print(json.dumps(rows, indent=2))
            else:
                for r in rows:
                    print(f"{'ok ' if r['exists'] else 'MISSING'}  {r['path'] or r['relative_path']}"
                          + (f"  (x{r['refs']})" if r["refs"] > 1 else ""))
                n_missing = sum(not r["exists"] for r in rows)
                print(f"{len(rows)} samples, {n_missing} missing", file=sys.stderr)
            return 0
        if a.cmd == "set-tempo":
            set_tempo(tree, float(a.bpm))
            msg = f"tempo -> {a.bpm}"
            if summary(tree)["tempo_automated"]:
                msg += " (note: the set has tempo automation, which overrides this)"
        elif a.cmd == "rename-track":
            rename_track(tree, a.track, a.new_name)
            msg = f"renamed {a.track!r} -> {a.new_name!r}"
        elif a.cmd == "set-color":
            set_track_color(tree, a.track, int(a.color))
            msg = f"color of {a.track!r} -> {a.color}"
        elif a.cmd == "relink":
            n = relink_samples(tree, a.old, a.new)
            msg = f"relinked {n} sample reference(s)"
        save(tree, a.output)
        print(f"{msg}; wrote {a.output}")
        return 0
    except (AlsError, OSError, ET.ParseError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
