"""
Tests for als.py against tiny synthetic Live Sets (a Live 12 and a Live 10 layout), so they don't
depend on anyone's music folder:

    python tools/test_als.py
"""

from __future__ import annotations

import gzip
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import als  # noqa: E402

# Live 12: MainTrack, <Color>, <Scenes>, FileRef/Path. A quote in an attribute -> single quotes.
LIVE12 = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="12.0_12120" Creator="Ableton Live 12.1.1" Revision="x">
\t<LiveSet>
\t\t<Tracks>
\t\t\t<MidiTrack Id="1">
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="1-Bass" />
\t\t\t\t\t<UserName Value="" />
\t\t\t\t</Name>
\t\t\t\t<Color Value="3" />
\t\t\t\t<TrackGroupId Value="-1" />
\t\t\t\t<ViewData Value='{"a": 1}' />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<MainSequencer>
\t\t\t\t\t\t<ClipSlotList>
\t\t\t\t\t\t\t<ClipSlot Id="0">
\t\t\t\t\t\t\t\t<ClipSlot>
\t\t\t\t\t\t\t\t\t<Value>
\t\t\t\t\t\t\t\t\t\t<MidiClip Id="0" Time="0" />
\t\t\t\t\t\t\t\t\t</Value>
\t\t\t\t\t\t\t\t</ClipSlot>
\t\t\t\t\t\t\t</ClipSlot>
\t\t\t\t\t\t\t<ClipSlot Id="1">
\t\t\t\t\t\t\t\t<ClipSlot>
\t\t\t\t\t\t\t\t\t<Value />
\t\t\t\t\t\t\t\t</ClipSlot>
\t\t\t\t\t\t\t</ClipSlot>
\t\t\t\t\t\t</ClipSlotList>
\t\t\t\t\t\t<ClipTimeable>
\t\t\t\t\t\t\t<ArrangerAutomation>
\t\t\t\t\t\t\t\t<Events>
\t\t\t\t\t\t\t\t\t<MidiClip Id="1" Time="0" />
\t\t\t\t\t\t\t\t\t<MidiClip Id="2" Time="16" />
\t\t\t\t\t\t\t\t</Events>
\t\t\t\t\t\t\t</ArrangerAutomation>
\t\t\t\t\t\t</ClipTimeable>
\t\t\t\t\t</MainSequencer>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices>
\t\t\t\t\t\t\t<OriginalSimpler Id="0">
\t\t\t\t\t\t\t\t<UserName Value="Sub" />
\t\t\t\t\t\t\t\t<SampleRef>
\t\t\t\t\t\t\t\t\t<FileRef>
\t\t\t\t\t\t\t\t\t\t<RelativePathType Value="3" />
\t\t\t\t\t\t\t\t\t\t<RelativePath Value="Samples/kick.wav" />
\t\t\t\t\t\t\t\t\t\t<Path Value="{old}/Samples/kick.wav" />
\t\t\t\t\t\t\t\t\t</FileRef>
\t\t\t\t\t\t\t\t</SampleRef>
\t\t\t\t\t\t\t</OriginalSimpler>
\t\t\t\t\t\t\t<PluginDevice Id="1">
\t\t\t\t\t\t\t\t<UserName Value="" />
\t\t\t\t\t\t\t\t<PluginDesc>
\t\t\t\t\t\t\t\t\t<Vst3PluginInfo Id="0">
\t\t\t\t\t\t\t\t\t\t<Name Value="Serum" />
\t\t\t\t\t\t\t\t\t</Vst3PluginInfo>
\t\t\t\t\t\t\t\t</PluginDesc>
\t\t\t\t\t\t\t</PluginDevice>
\t\t\t\t\t\t</Devices>
\t\t\t\t\t</DeviceChain>
\t\t\t\t</DeviceChain>
\t\t\t</MidiTrack>
\t\t\t<AudioTrack Id="2">
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="Vox &amp; Co" />
\t\t\t\t\t<UserName Value="Vox &amp; Co" />
\t\t\t\t</Name>
\t\t\t\t<Color Value="9" />
\t\t\t\t<TrackGroupId Value="-1" />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<MainSequencer>
\t\t\t\t\t\t<ClipSlotList />
\t\t\t\t\t\t<Sample>
\t\t\t\t\t\t\t<ArrangerAutomation>
\t\t\t\t\t\t\t\t<Events>
\t\t\t\t\t\t\t\t\t<AudioClip Id="0" Time="0">
\t\t\t\t\t\t\t\t\t\t<SampleRef>
\t\t\t\t\t\t\t\t\t\t\t<FileRef>
\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathType Value="1" />
\t\t\t\t\t\t\t\t\t\t\t\t<RelativePath Value="../gone.wav" />
\t\t\t\t\t\t\t\t\t\t\t\t<Path Value="/nowhere/gone.wav" />
\t\t\t\t\t\t\t\t\t\t\t</FileRef>
\t\t\t\t\t\t\t\t\t\t</SampleRef>
\t\t\t\t\t\t\t\t\t</AudioClip>
\t\t\t\t\t\t\t\t</Events>
\t\t\t\t\t\t\t</ArrangerAutomation>
\t\t\t\t\t\t</Sample>
\t\t\t\t\t</MainSequencer>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices />
\t\t\t\t\t</DeviceChain>
\t\t\t\t</DeviceChain>
\t\t\t</AudioTrack>
\t\t\t<ReturnTrack Id="3">
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="A-Reverb" />
\t\t\t\t\t<UserName Value="" />
\t\t\t\t</Name>
\t\t\t\t<Color Value="16" />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices>
\t\t\t\t\t\t\t<Reverb Id="0">
\t\t\t\t\t\t\t\t<UserName Value="" />
\t\t\t\t\t\t\t</Reverb>
\t\t\t\t\t\t</Devices>
\t\t\t\t\t</DeviceChain>
\t\t\t\t</DeviceChain>
\t\t\t</ReturnTrack>
\t\t</Tracks>
\t\t<MainTrack>
\t\t\t<AutomationEnvelopes>
\t\t\t\t<Envelopes>
\t\t\t\t\t<AutomationEnvelope Id="0">
\t\t\t\t\t\t<EnvelopeTarget>
\t\t\t\t\t\t\t<PointeeId Value="8" />
\t\t\t\t\t\t</EnvelopeTarget>
\t\t\t\t\t\t<Automation>
\t\t\t\t\t\t\t<Events>
\t\t\t\t\t\t\t\t<FloatEvent Id="1" Time="-63072000" Value="120" />
\t\t\t\t\t\t\t</Events>
\t\t\t\t\t\t</Automation>
\t\t\t\t\t</AutomationEnvelope>
\t\t\t\t</Envelopes>
\t\t\t</AutomationEnvelopes>
\t\t\t<Name>
\t\t\t\t<EffectiveName Value="Main" />
\t\t\t\t<UserName Value="" />
\t\t\t</Name>
\t\t\t<DeviceChain>
\t\t\t\t<Mixer>
\t\t\t\t\t<Tempo>
\t\t\t\t\t\t<Manual Value="120" />
\t\t\t\t\t\t<AutomationTarget Id="8" />
\t\t\t\t\t</Tempo>
\t\t\t\t\t<TimeSignature>
\t\t\t\t\t\t<Manual Value="302" />
\t\t\t\t\t</TimeSignature>
\t\t\t\t</Mixer>
\t\t\t\t<DeviceChain>
\t\t\t\t\t<Devices>
\t\t\t\t\t\t<Limiter Id="0">
\t\t\t\t\t\t\t<UserName Value="" />
\t\t\t\t\t\t</Limiter>
\t\t\t\t\t</Devices>
\t\t\t\t</DeviceChain>
\t\t\t</DeviceChain>
\t\t</MainTrack>
\t\t<Scenes>
\t\t\t<Scene Id="0">
\t\t\t\t<Name Value="Intro" />
\t\t\t</Scene>
\t\t\t<Scene Id="1">
\t\t\t\t<Name Value="" />
\t\t\t</Scene>
\t\t</Scenes>
\t\t<Locators>
\t\t\t<Locators>
\t\t\t\t<Locator Id="0">
\t\t\t\t\t<Time Value="32" />
\t\t\t\t\t<Name Value="Drop" />
\t\t\t\t</Locator>
\t\t\t</Locators>
\t\t</Locators>
\t</LiveSet>
</Ableton>
"""

# Live 10: MasterTrack, <ColorIndex>, <SceneNames>, FileRef as dir elements + Name, &quot;.
LIVE10 = """<?xml version="1.0" encoding="UTF-8"?>
<Ableton MajorVersion="5" MinorVersion="10.0_377" Creator="Ableton Live 10.1.43" Revision="x">
\t<LiveSet>
\t\t<Tracks>
\t\t\t<GroupTrack Id="1">
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="1-Group" />
\t\t\t\t\t<UserName Value="" />
\t\t\t\t</Name>
\t\t\t\t<ColorIndex Value="141" />
\t\t\t\t<TrackGroupId Value="-1" />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices />
\t\t\t\t\t</DeviceChain>
\t\t\t\t</DeviceChain>
\t\t\t</GroupTrack>
\t\t\t<AudioTrack Id="2">
\t\t\t\t<Name>
\t\t\t\t\t<EffectiveName Value="say &quot;hi&quot;" />
\t\t\t\t\t<UserName Value="say &quot;hi&quot;" />
\t\t\t\t</Name>
\t\t\t\t<ColorIndex Value="150" />
\t\t\t\t<TrackGroupId Value="1" />
\t\t\t\t<DeviceChain>
\t\t\t\t\t<MainSequencer>
\t\t\t\t\t\t<ClipSlotList />
\t\t\t\t\t\t<Sample>
\t\t\t\t\t\t\t<ArrangerAutomation>
\t\t\t\t\t\t\t\t<Events>
\t\t\t\t\t\t\t\t\t<AudioClip Id="0" Time="0">
\t\t\t\t\t\t\t\t\t\t<SampleRef>
\t\t\t\t\t\t\t\t\t\t\t<FileRef>
\t\t\t\t\t\t\t\t\t\t\t\t<HasRelativePath Value="true" />
\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathType Value="1" />
\t\t\t\t\t\t\t\t\t\t\t\t<RelativePath>
\t\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathElement Id="1" Dir="" />
\t\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathElement Id="2" Dir="Loops" />
\t\t\t\t\t\t\t\t\t\t\t\t</RelativePath>
\t\t\t\t\t\t\t\t\t\t\t\t<Name Value="loop.aif" />
\t\t\t\t\t\t\t\t\t\t\t\t<Data>
\t\t\t\t\t\t\t\t\t\t\t\t\t00FF
\t\t\t\t\t\t\t\t\t\t\t\t</Data>
\t\t\t\t\t\t\t\t\t\t\t\t<SearchHint>
\t\t\t\t\t\t\t\t\t\t\t\t\t<PathHint>
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathElement Id="8" Dir="Users" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathElement Id="9" Dir="me" />
\t\t\t\t\t\t\t\t\t\t\t\t\t\t<RelativePathElement Id="10" Dir="Loops" />
\t\t\t\t\t\t\t\t\t\t\t\t\t</PathHint>
\t\t\t\t\t\t\t\t\t\t\t\t</SearchHint>
\t\t\t\t\t\t\t\t\t\t\t</FileRef>
\t\t\t\t\t\t\t\t\t\t</SampleRef>
\t\t\t\t\t\t\t\t\t</AudioClip>
\t\t\t\t\t\t\t\t</Events>
\t\t\t\t\t\t\t</ArrangerAutomation>
\t\t\t\t\t\t</Sample>
\t\t\t\t\t</MainSequencer>
\t\t\t\t\t<DeviceChain>
\t\t\t\t\t\t<Devices />
\t\t\t\t\t</DeviceChain>
\t\t\t\t</DeviceChain>
\t\t\t</AudioTrack>
\t\t</Tracks>
\t\t<MasterTrack>
\t\t\t<Name>
\t\t\t\t<EffectiveName Value="Master" />
\t\t\t\t<UserName Value="" />
\t\t\t</Name>
\t\t\t<DeviceChain>
\t\t\t\t<Mixer>
\t\t\t\t\t<Tempo>
\t\t\t\t\t\t<Manual Value="90" />
\t\t\t\t\t</Tempo>
\t\t\t\t\t<TimeSignature>
\t\t\t\t\t\t<Manual Value="201" />
\t\t\t\t\t</TimeSignature>
\t\t\t\t</Mixer>
\t\t\t\t<DeviceChain>
\t\t\t\t\t<Devices />
\t\t\t\t</DeviceChain>
\t\t\t</DeviceChain>
\t\t</MasterTrack>
\t\t<SceneNames>
\t\t\t<Scene Id="0" Value="Verse" />
\t\t</SceneNames>
\t\t<Locators>
\t\t\t<Locators />
\t\t</Locators>
\t</LiveSet>
</Ableton>
"""


def write_als(path: str, xml: str) -> bytes:
    raw = xml.encode("utf-8")
    with open(path, "wb") as f:
        f.write(gzip.compress(raw))
    return raw


def raw_of(path: str) -> bytes:
    return gzip.decompress(open(path, "rb").read())


def test_live12(d: str) -> None:
    proj = os.path.join(d, "song Project")
    os.makedirs(os.path.join(proj, "Samples"))
    open(os.path.join(proj, "Samples", "kick.wav"), "wb").close()
    src = os.path.join(proj, "song.als")
    raw = write_als(src, LIVE12.replace("{old}", proj))
    before = open(src, "rb").read()

    t = als.load(src)
    assert als.to_bytes(t) == raw, "unedited round trip must be byte-identical"

    s = als.summary(t)
    assert s["creator"] == "Ableton Live 12.1.1" and s["minor_version"] == "12.0_12120"
    assert s["tempo"] == 120 and s["tempo_automated"] is False
    assert s["time_signature"] == "6/8"
    assert [(x["type"], x["name"], x["color"]) for x in s["tracks"]] == [
        ("midi", "1-Bass", 3), ("audio", "Vox & Co", 9)]
    assert s["tracks"][0]["devices"] == [{"type": "OriginalSimpler", "name": "Sub"},
                                         {"type": "PluginDevice", "name": "Serum"}]
    assert (s["tracks"][0]["session_clips"], s["tracks"][0]["arrangement_clips"]) == (1, 2)
    assert (s["tracks"][1]["session_clips"], s["tracks"][1]["arrangement_clips"]) == (0, 1)
    assert s["returns"] == [{"index": -2, "type": "return", "name": "A-Reverb",
                             "effective_name": "A-Reverb", "color": 16,
                             "devices": [{"type": "Reverb", "name": ""}]}]
    assert s["main"]["devices"] == [{"type": "Limiter", "name": ""}]
    assert s["scenes"] == ["Intro", ""]
    assert s["locators"] == [{"name": "Drop", "time": 32}]

    samples = {os.path.basename(r["path"]): r for r in als.list_samples(t)}
    assert samples["kick.wav"]["exists"] and not samples["gone.wav"]["exists"]

    # edits
    als.set_tempo(t, 128.5)
    als.rename_track(t, "vox & co", 'Lead "Vox"')          # by name, case-insensitive
    als.rename_track(t, -2, "Verb")                        # return A
    als.set_track_color(t, 0, 42)
    assert als.relink_samples(t, "/nowhere/", "/Volumes/ext/") == 1
    out = os.path.join(d, "out12.als")
    als.save(t, out)
    assert open(src, "rb").read() == before, "input must be untouched"

    t2 = als.load(out)
    s2 = als.summary(t2)
    assert s2["tempo"] == 128.5
    assert s2["tracks"][1]["name"] == 'Lead "Vox"' and s2["returns"][0]["name"] == "Verb"
    assert s2["tracks"][0]["color"] == 42
    assert "/Volumes/ext/gone.wav" in [r["path"] for r in als.list_samples(t2)]
    new = raw_of(out)
    assert b'<FloatEvent Id="1" Time="-63072000" Value="128.5" />' in new
    assert b"<UserName Value='Lead \"Vox\"' />" in new     # Live 11/12 quoting
    # nothing else changed: the expected edits turn the new file back into the original
    undo = (new.replace(b"128.5", b"120")
               .replace(b"<EffectiveName Value='Lead \"Vox\"' />", b'<EffectiveName Value="Vox &amp; Co" />')
               .replace(b"<UserName Value='Lead \"Vox\"' />", b'<UserName Value="Vox &amp; Co" />')
               .replace(b'<EffectiveName Value="Verb" />', b'<EffectiveName Value="A-Reverb" />')
               .replace(b'<UserName Value="Verb" />', b'<UserName Value="" />', 1)
               .replace(b'<Color Value="42" />', b'<Color Value="3" />')
               .replace(b"/Volumes/ext/", b"/nowhere/"))
    assert undo == raw, "unexpected changes beyond the edits"

    try:
        als.rename_track(t2, "no such track", "x")
        raise AssertionError("expected AlsError")
    except als.AlsError:
        pass


def test_live10(d: str) -> None:
    src = os.path.join(d, "old.als")
    raw = write_als(src, LIVE10)
    t = als.load(src)
    assert als.to_bytes(t) == raw

    s = als.summary(t)
    assert s["tempo"] == 90 and s["time_signature"] == "4/4" and s["scenes"] == ["Verse"]
    assert [(x["type"], x["name"], x["color"], x["group_id"]) for x in s["tracks"]] == [
        ("group", "1-Group", 141, -1), ("audio", 'say "hi"', 150, 1)]
    assert s["tracks"][1]["arrangement_clips"] == 1 and s["main"]["name"] == "Master"
    (smp,) = als.list_samples(t)
    assert smp["path"] == "/Users/me/Loops/loop.aif" and smp["relative_path"] == "../Loops/loop.aif"

    als.set_tempo(t, 100)
    als.set_track_color(t, '1', 7)
    assert als.relink_samples(t, "/Users/me/", "/Volumes/Archive/Sets/") == 1
    out = os.path.join(d, "out10.als")
    als.save(t, out)
    t2 = als.load(out)
    s2 = als.summary(t2)
    assert s2["tempo"] == 100 and s2["tracks"][1]["color"] == 7
    assert als.list_samples(t2)[0]["path"] == "/Volumes/Archive/Sets/Loops/loop.aif"
    new = raw_of(out)
    assert b'EffectiveName Value="say &quot;hi&quot;"' in new   # Live 10 quoting kept
    assert (b'<PathHint>\n' + b'\t' * 14 + b'<RelativePathElement Id="8" Dir="Volumes" />') in new
    assert new.count(b"<RelativePathElement") == 6 and b"\t</PathHint>" in new


def test_cli(d: str) -> None:
    src = os.path.join(d, "cli.als")
    write_als(src, LIVE12.replace("{old}", "/x"))
    before = open(src, "rb").read()
    cli = [sys.executable, os.path.join(HERE, "als.py")]
    r = subprocess.run(cli + ["summary", src], capture_output=True, text=True)
    assert r.returncode == 0 and "tempo 120" in r.stdout, r.stderr
    r = subprocess.run(cli + ["set-tempo", src, "99"], capture_output=True, text=True)
    assert r.returncode != 0, "edits require -o"
    out = os.path.join(d, "cli-out.als")
    r = subprocess.run(cli + ["rename-track", src, "0", "Sub", "-o", out], capture_output=True,
                       text=True)
    assert r.returncode == 0, r.stderr
    assert als.summary(als.load(out))["tracks"][0]["name"] == "Sub"
    r = subprocess.run(cli + ["samples", src, "--missing"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.count("MISSING") == 2
    assert open(src, "rb").read() == before
    assert not [f for f in os.listdir(d) if f.endswith(".tmp")], "temp files left behind"


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        test_live12(d)
        test_live10(d)
        test_cli(d)
    print("ok")
