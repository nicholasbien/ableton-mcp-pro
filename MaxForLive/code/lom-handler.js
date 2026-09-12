// lom-handler.js — Max JS (ES5) LiveAPI command handler for AbletonMCP
// Runs inside Max's js object. All LiveAPI calls happen here.

autowatch = 1;
var HANDLER_VERSION = "2026-09-12.1";
inlets = 1;
outlets = 1;

// Command queue — process one at a time
var commandQueue = [];
var processing = false;

// ─── Inlet handler ───
// Receives: command <requestId> <jsonString>

function command() {
    // Collect all arguments — requestId is first, rest is JSON string (may be split by spaces)
    var args = arrayfromargs(messagename, arguments);
    // args[0] = "command", args[1] = requestId, args[2..] = JSON string parts
    var requestId = String(args[1]);
    var jsonStr = args.slice(2).join(" ");

    commandQueue.push({ requestId: requestId, jsonStr: jsonStr });
    if (!processing) {
        processNext();
    }
}

function processNext() {
    if (commandQueue.length === 0) {
        processing = false;
        return;
    }
    processing = true;
    var item = commandQueue.shift();
    var requestId = item.requestId;

    var cmdType = "";
    var params = {};
    try {
        var parsed = JSON.parse(item.jsonStr);
        cmdType = parsed.type || "";
        params = parsed.params || {};
    } catch (e) {
        post("Error parsing command JSON: " + e + "\n");
    }

    var result;
    try {
        result = dispatch(String(cmdType), params);
    } catch (e) {
        finishCommand(requestId, null, e);
        return;
    }

    if (result && result.__deferred === true) {
        // Long-running command: it will call resolve/reject later (from a Task).
        // The queue stays blocked until then so commands run strictly in order.
        result.start(
            function (value) { finishCommand(requestId, value, null); },
            function (err) { finishCommand(requestId, null, err); }
        );
        return;
    }

    finishCommand(requestId, result, null);
}

function finishCommand(requestId, result, err) {
    var responseJson;
    if (err !== null && err !== undefined) {
        responseJson = JSON.stringify({ status: "error", message: String(err) });
    } else {
        responseJson = JSON.stringify({ status: "success", result: result });
    }
    outlet(0, "response", requestId, responseJson);

    // Process next command on next tick to avoid stack overflow
    var t = new Task(processNext);
    t.schedule(1);
}

// Wrap a long-running operation. `starter(resolve, reject)` must eventually call one of them.
function deferred(starter) {
    return { __deferred: true, start: starter };
}

// Handle anything function — catch messages that aren't "command"
function anything() {
    // ignore
}

// ─── Track path resolution ───

function getTrackPath(trackIndex) {
    if (trackIndex === -1) return "live_set master_track";
    if (trackIndex <= -2) return "live_set return_tracks " + (-(trackIndex + 2));
    return "live_set tracks " + trackIndex;
}

function getTrack(trackIndex) {
    return new LiveAPI(getTrackPath(trackIndex));
}

// ─── Command dispatch ───

function dispatch(cmdType, params) {
    switch (cmdType) {
        // Read commands
        case "ping": return { backend: "m4l", handler_version: HANDLER_VERSION, live_version: liveVersion() };
        case "get_session_info": return cmd_get_session_info(params);
        case "get_track_info": return cmd_get_track_info(params);
        case "get_device_parameters": return cmd_get_device_parameters(params);
        case "get_arrangement_info": return cmd_get_arrangement_info(params);
        case "get_arrangement_clips": return cmd_get_arrangement_clips(params);
        case "get_full_arrangement": return cmd_get_full_arrangement(params);
        case "get_clip_notes": return cmd_get_clip_notes(params);
        case "get_arrangement_clip_notes": return cmd_get_arrangement_clip_notes(params);
        case "get_track_routing": return cmd_get_track_routing(params);
        case "get_clip_envelope": return cmd_get_clip_envelope(params);
        case "get_browser_tree": return cmd_get_browser_tree(params);
        case "get_browser_items_at_path": return cmd_get_browser_items_at_path(params);

        // Simple write commands
        case "set_tempo": return cmd_set_tempo(params);
        case "set_time_signature": return cmd_set_time_signature(params);
        case "set_metronome": return cmd_set_metronome(params);
        case "set_track_name": return cmd_set_track_name(params);
        case "set_track_volume": return cmd_set_track_volume(params);
        case "set_track_panning": return cmd_set_track_panning(params);
        case "set_track_mute": return cmd_set_track_mute(params);
        case "set_track_solo": return cmd_set_track_solo(params);
        case "set_track_arm": return cmd_set_track_arm(params);
        case "set_send_level": return cmd_set_send_level(params);
        case "set_track_monitoring": return cmd_set_track_monitoring(params);
        case "set_track_input_routing": return cmd_set_track_input_routing(params);
        case "set_track_output_routing": return cmd_set_track_output_routing(params);
        case "start_playback": return cmd_start_playback(params);
        case "stop_playback": return cmd_stop_playback(params);
        case "play_arrangement": return cmd_play_arrangement(params);
        case "set_song_time": return cmd_set_song_time(params);
        case "set_record_mode": return cmd_set_record_mode(params);
        case "set_arrangement_overdub": return cmd_set_arrangement_overdub(params);
        case "set_back_to_arranger": return cmd_set_back_to_arranger(params);
        case "set_arrangement_loop": return cmd_set_arrangement_loop(params);
        case "undo": return cmd_undo(params);
        case "redo": return cmd_redo(params);

        // Track/Scene/Clip management
        case "create_midi_track": return cmd_create_midi_track(params);
        case "create_audio_track": return cmd_create_audio_track(params);
        case "delete_track": return cmd_delete_track(params);
        case "duplicate_track": return cmd_duplicate_track(params);
        case "create_scene": return cmd_create_scene(params);
        case "delete_scene": return cmd_delete_scene(params);
        case "set_scene_name": return cmd_set_scene_name(params);
        case "fire_scene": return cmd_fire_scene(params);
        case "create_clip": return cmd_create_clip(params);
        case "create_audio_clip": return cmd_create_audio_clip(params);
        case "delete_clip": return cmd_delete_clip(params);
        case "duplicate_clip": return cmd_duplicate_clip(params);
        case "set_clip_name": return cmd_set_clip_name(params);
        case "set_clip_loop": return cmd_set_clip_loop(params);
        case "fire_clip": return cmd_fire_clip(params);
        case "stop_clip": return cmd_stop_clip(params);
        case "add_notes_to_clip": return cmd_add_notes_to_clip(params);
        case "create_arrangement_midi_clip": return cmd_create_arrangement_midi_clip(params);
        case "create_arrangement_audio_clip": return cmd_create_arrangement_audio_clip(params);
        case "delete_arrangement_clip": return cmd_delete_arrangement_clip(params);
        case "record_arrangement": return cmd_record_arrangement(params);

        // Devices, Browser & Automation
        case "set_device_parameter": return cmd_set_device_parameter(params);
        case "batch_set_device_parameters": return cmd_batch_set_device_parameters(params);
        case "delete_device": return cmd_delete_device(params);
        case "load_instrument_or_effect": return cmd_load_instrument_or_effect(params);
        case "load_browser_item": return cmd_load_instrument_or_effect(params);
        case "set_clip_envelope": return cmd_set_clip_envelope(params);
        case "clear_clip_envelope": return cmd_clear_clip_envelope(params);

        default:
            throw "Unknown command: " + cmdType;
    }
}

// ─── Helpers ───

function liveVersion() {
    var app = new LiveAPI("live_app");
    var v = [app.call("get_major_version"), app.call("get_minor_version"), app.call("get_bugfix_version")];
    for (var i = 0; i < v.length; i++) v[i] = (v[i] instanceof Array) ? v[i][0] : v[i];
    return v.join(".");
}

function apiGet(path, prop) {
    var api = new LiveAPI(path);
    return api.get(prop);
}

function apiGetStr(path, prop) {
    var val = apiGet(path, prop);
    if (val instanceof Array) return val.join(" ");
    return String(val);
}

function apiGetNum(path, prop) {
    var val = apiGet(path, prop);
    if (val instanceof Array) return Number(val[0]);
    return Number(val);
}

function apiGetCount(path, child) {
    var api = new LiveAPI(path);
    return api.getcount(child);
}

function param(params, key, defaultVal) {
    var v = params[key];
    if (v === undefined || v === null) return defaultVal;
    return v;
}

// ─── Read Commands ───

function cmd_get_session_info() {
    var song = new LiveAPI("live_set");
    var tempo = apiGetNum("live_set", "tempo");
    var sigNum = apiGetNum("live_set", "signature_numerator");
    var sigDen = apiGetNum("live_set", "signature_denominator");
    var trackCount = apiGetCount("live_set", "tracks");
    var returnCount = apiGetCount("live_set", "return_tracks");

    var master = new LiveAPI("live_set master_track");
    var masterVol = apiGetNum("live_set master_track mixer_device volume", "value");
    var masterPan = apiGetNum("live_set master_track mixer_device panning", "value");

    return {
        tempo: tempo,
        signature_numerator: sigNum,
        signature_denominator: sigDen,
        track_count: trackCount,
        return_track_count: returnCount,
        master_track: {
            name: "Master",
            volume: masterVol,
            panning: masterPan
        }
    };
}

function cmd_get_track_info(params) {
    var trackIndex = param(params, "track_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var track = new LiveAPI(trackPath);

    if (!track.id || track.id === "0") {
        throw "Track index out of range";
    }

    var name = apiGetStr(trackPath, "name");
    var hasAudioInput = apiGetNum(trackPath, "has_audio_input");
    var hasMidiInput = apiGetNum(trackPath, "has_midi_input");
    var mute = apiGetNum(trackPath, "mute");
    var solo = apiGetNum(trackPath, "solo");
    var arm = apiGetNum(trackPath, "arm");
    var volume = apiGetNum(trackPath + " mixer_device volume", "value");
    var panning = apiGetNum(trackPath + " mixer_device panning", "value");

    // Get clip slots
    var slotCount = apiGetCount(trackPath, "clip_slots");
    var clipSlots = [];
    for (var i = 0; i < slotCount; i++) {
        var slotPath = trackPath + " clip_slots " + i;
        var hasClip = apiGetNum(slotPath, "has_clip");
        var clipInfo = null;
        if (hasClip) {
            var clipPath = slotPath + " clip";
            clipInfo = {
                name: apiGetStr(clipPath, "name"),
                length: apiGetNum(clipPath, "length"),
                is_playing: apiGetNum(clipPath, "is_playing") ? true : false,
                is_recording: apiGetNum(clipPath, "is_recording") ? true : false
            };
        }
        clipSlots.push({
            index: i,
            has_clip: hasClip ? true : false,
            clip: clipInfo
        });
    }

    // Get devices
    var deviceCount = apiGetCount(trackPath, "devices");
    var devices = [];
    for (var d = 0; d < deviceCount; d++) {
        var devPath = trackPath + " devices " + d;
        var devName = apiGetStr(devPath, "name");
        var className = apiGetStr(devPath, "class_name");
        var devType = getDeviceType(devPath);
        devices.push({
            index: d,
            name: devName,
            class_name: className,
            type: devType
        });
    }

    return {
        index: trackIndex,
        name: name,
        is_audio_track: hasAudioInput ? true : false,
        is_midi_track: hasMidiInput ? true : false,
        mute: mute ? true : false,
        solo: solo ? true : false,
        arm: arm ? true : false,
        volume: volume,
        panning: panning,
        clip_slots: clipSlots,
        devices: devices
    };
}

function getDeviceType(devPath) {
    try {
        var canDrumPads = apiGetNum(devPath, "can_have_drum_pads");
        if (canDrumPads) return "drum_machine";
        var canChains = apiGetNum(devPath, "can_have_chains");
        if (canChains) return "rack";
        var classDisplay = apiGetStr(devPath, "class_display_name");
        if (classDisplay.toLowerCase().indexOf("instrument") >= 0) return "instrument";
        var className = apiGetStr(devPath, "class_name");
        if (className.toLowerCase().indexOf("audio_effect") >= 0) return "audio_effect";
        if (className.toLowerCase().indexOf("midi_effect") >= 0) return "midi_effect";
        return "unknown";
    } catch (e) {
        return "unknown";
    }
}

function cmd_get_device_parameters(params) {
    var trackIndex = param(params, "track_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var devPath = trackPath + " devices " + deviceIndex;

    var dev = new LiveAPI(devPath);
    if (!dev.id || dev.id === "0") throw "Device index out of range";

    var trackName = apiGetStr(trackPath, "name");
    var devName = apiGetStr(devPath, "name");
    var paramCount = apiGetCount(devPath, "parameters");
    var parameters = [];

    for (var i = 0; i < paramCount; i++) {
        var pPath = devPath + " parameters " + i;
        var pName = apiGetStr(pPath, "name");
        var pVal = apiGetNum(pPath, "value");
        var pMin = apiGetNum(pPath, "min");
        var pMax = apiGetNum(pPath, "max");
        var pIsQuant = apiGetNum(pPath, "is_quantized");
        var pIsEnabled = apiGetNum(pPath, "is_enabled");
        var normVal = 0;
        if ((pMax - pMin) !== 0) {
            normVal = (pVal - pMin) / (pMax - pMin);
        }
        parameters.push({
            index: i,
            name: pName,
            value: pVal,
            normalized_value: normVal,
            min: pMin,
            max: pMax,
            is_quantized: pIsQuant ? true : false,
            is_enabled: pIsEnabled ? true : false
        });
    }

    return {
        track_index: trackIndex,
        track_name: trackName,
        device_index: deviceIndex,
        device_name: devName,
        parameters: parameters
    };
}

function cmd_get_arrangement_info() {
    return {
        current_song_time: apiGetNum("live_set", "current_song_time"),
        is_playing: apiGetNum("live_set", "is_playing") ? true : false,
        record_mode: apiGetNum("live_set", "record_mode") ? true : false,
        arrangement_overdub: apiGetNum("live_set", "arrangement_overdub") ? true : false,
        back_to_arranger: apiGetNum("live_set", "back_to_arranger") ? true : false,
        loop: apiGetNum("live_set", "loop") ? true : false,
        loop_start: apiGetNum("live_set", "loop_start"),
        loop_length: apiGetNum("live_set", "loop_length"),
        tempo: apiGetNum("live_set", "tempo"),
        scene_count: apiGetCount("live_set", "scenes"),
        song_length: apiGetNum("live_set", "song_length")
    };
}

function cmd_get_arrangement_clips(params) {
    var trackIndex = param(params, "track_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var trackName = apiGetStr(trackPath, "name");

    var clips = [];
    var clipCount = apiGetCount(trackPath, "arrangement_clips");
    for (var i = 0; i < clipCount; i++) {
        var clipPath = trackPath + " arrangement_clips " + i;
        clips.push({
            name: apiGetStr(clipPath, "name"),
            start_time: apiGetNum(clipPath, "start_time"),
            end_time: apiGetNum(clipPath, "end_time"),
            length: apiGetNum(clipPath, "length"),
            is_midi_clip: apiGetNum(clipPath, "is_midi_clip") ? true : false,
            is_audio_clip: apiGetNum(clipPath, "is_audio_clip") ? true : false
        });
    }

    return {
        track_index: trackIndex,
        track_name: trackName,
        arrangement_clip_count: clips.length,
        clips: clips
    };
}

function cmd_get_full_arrangement() {
    var trackCount = apiGetCount("live_set", "tracks");
    var tracksData = [];

    for (var i = 0; i < trackCount; i++) {
        var trackPath = "live_set tracks " + i;
        var clipCount = apiGetCount(trackPath, "arrangement_clips");
        if (clipCount === 0) continue;

        var clips = [];
        for (var c = 0; c < clipCount; c++) {
            var clipPath = trackPath + " arrangement_clips " + c;
            clips.push({
                name: apiGetStr(clipPath, "name"),
                start_time: apiGetNum(clipPath, "start_time"),
                end_time: apiGetNum(clipPath, "end_time"),
                length: apiGetNum(clipPath, "length"),
                is_midi_clip: apiGetNum(clipPath, "is_midi_clip") ? true : false
            });
        }

        tracksData.push({
            track_index: i,
            track_name: apiGetStr(trackPath, "name"),
            clips: clips
        });
    }

    var sceneCount = apiGetCount("live_set", "scenes");
    var scenes = [];
    for (var s = 0; s < sceneCount; s++) {
        scenes.push({
            index: s,
            name: apiGetStr("live_set scenes " + s, "name")
        });
    }

    return {
        tempo: apiGetNum("live_set", "tempo"),
        time_signature: apiGetNum("live_set", "signature_numerator") + "/" + apiGetNum("live_set", "signature_denominator"),
        song_length: apiGetNum("live_set", "song_length"),
        tracks_with_clips: tracksData,
        scenes: scenes
    };
}

function cmd_get_clip_notes(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var slotPath = trackPath + " clip_slots " + clipIndex;

    var hasClip = apiGetNum(slotPath, "has_clip");
    if (!hasClip) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var isMidi = apiGetNum(clipPath, "is_midi_clip");
    if (!isMidi) throw "Not a MIDI clip";

    var clipLength = apiGetNum(clipPath, "length");
    var clipName = apiGetStr(clipPath, "name");

    // Use get_notes to retrieve notes: returns [pitch, start, duration, velocity, mute, ...]
    var clip = new LiveAPI(clipPath);
    clip.call("select_all_notes");
    var rawNotes = clip.call("get_selected_notes");

    var noteList = [];
    // get_selected_notes returns: "notes" count pitch start duration velocity mute [repeated] "done"
    if (rawNotes && rawNotes.length > 2) {
        var count = Number(rawNotes[1]);
        var idx = 2; // skip "notes" and count
        for (var n = 0; n < count; n++) {
            if (idx + 5 > rawNotes.length) break;
            noteList.push({
                pitch: Number(rawNotes[idx + 1]),
                start_time: Number(rawNotes[idx + 2]),
                duration: Number(rawNotes[idx + 3]),
                velocity: Number(rawNotes[idx + 4]),
                mute: false
            });
            idx += 6; // skip "note" pitch start dur vel mute
        }
    }

    clip.call("deselect_all_notes");

    return {
        track_index: trackIndex,
        clip_index: clipIndex,
        clip_name: clipName,
        length: clipLength,
        note_count: noteList.length,
        notes: noteList
    };
}

function cmd_get_clip_envelope(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var parameterIndex = param(params, "parameter_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var slotPath = trackPath + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var devPath = trackPath + " devices " + deviceIndex;
    var pPath = devPath + " parameters " + parameterIndex;
    var paramName = apiGetStr(pPath, "name");
    var pMin = apiGetNum(pPath, "min");
    var pMax = apiGetNum(pPath, "max");
    var paramRange = pMax - pMin;

    var clipLength = apiGetNum(clipPath, "length");

    // Try to get automation envelope via the clip
    var clip = new LiveAPI(clipPath);
    var paramApi = new LiveAPI(pPath);

    // Use automation_envelope — may return null/0 if no envelope exists
    var envId = clip.call("automation_envelope", "id", paramApi.id);
    if (!envId || envId === "0" || envId === 0) {
        return {
            track_index: trackIndex,
            clip_index: clipIndex,
            parameter_name: paramName,
            has_envelope: false,
            points: []
        };
    }

    // Sample the envelope at regular intervals
    var numSamples = Math.min(Math.floor(clipLength), 64);
    if (numSamples < 1) numSamples = 1;
    var step = clipLength / numSamples;
    var points = [];

    var envApi = new LiveAPI("id " + envId);
    for (var i = 0; i < numSamples; i++) {
        var t = i * step;
        var val = Number(envApi.call("value_at_time", t));
        var normalized = paramRange > 0 ? (val - pMin) / paramRange : 0;
        points.push({
            time: Math.round(t * 1000) / 1000,
            value: Math.round(normalized * 10000) / 10000
        });
    }

    return {
        track_index: trackIndex,
        clip_index: clipIndex,
        parameter_name: paramName,
        has_envelope: true,
        points: points
    };
}

// Browser categories are named properties on the browser object
var BROWSER_CATEGORIES = ["instruments", "sounds", "drums", "audio_effects", "midi_effects"];
var BROWSER_CATEGORY_LABELS = {
    "instruments": "Instruments",
    "sounds": "Sounds",
    "drums": "Drums",
    "audio_effects": "Audio Effects",
    "midi_effects": "MIDI Effects"
};

// Get a LiveAPI for a browser category by name.
// "live_app browser" doesn't work as a path — browser is a property returning an object id.
function getBrowserCategory(catName) {
    // Browser is NOT accessible from M4L's JS LiveAPI.
    // Application.browser is only available from Python Remote Scripts.
    // Returns null — browser commands will return friendly error messages.
    return null;
}

function cmd_get_browser_tree(params) {
    throw "Browser is not accessible from Max for Live devices. Use the Remote Script instead, or drag instruments manually from Ableton's browser.";
}

function cmd_get_browser_items_at_path(params) {
    throw "Browser is not accessible from Max for Live devices. Use the Remote Script instead, or drag instruments manually from Ableton's browser.";
}

// ─── Simple Write Commands ───

function cmd_set_tempo(params) {
    var tempo = param(params, "tempo", 120.0);
    var song = new LiveAPI("live_set");
    song.set("tempo", tempo);
    return { tempo: apiGetNum("live_set", "tempo") };
}

function cmd_set_time_signature(params) {
    var numerator = param(params, "numerator", 4);
    var denominator = param(params, "denominator", 4);
    var song = new LiveAPI("live_set");
    song.set("signature_numerator", Math.floor(numerator));
    song.set("signature_denominator", Math.floor(denominator));
    return {
        numerator: apiGetNum("live_set", "signature_numerator"),
        denominator: apiGetNum("live_set", "signature_denominator")
    };
}

function cmd_set_metronome(params) {
    var on = param(params, "on", false);
    var song = new LiveAPI("live_set");
    song.set("metronome", on ? 1 : 0);
    return { metronome: apiGetNum("live_set", "metronome") ? true : false };
}

function cmd_set_track_name(params) {
    var trackIndex = param(params, "track_index", 0);
    var name = param(params, "name", "");
    var trackPath = getTrackPath(trackIndex);
    var track = new LiveAPI(trackPath);
    track.set("name", name);
    return { name: apiGetStr(trackPath, "name") };
}

function cmd_set_track_volume(params) {
    var trackIndex = param(params, "track_index", 0);
    var volume = param(params, "volume", 0.85);
    if (volume < 0.0 || volume > 1.0) throw "Volume must be between 0.0 and 1.0";

    var trackPath = getTrackPath(trackIndex);
    var volPath = trackPath + " mixer_device volume";
    var volMin = apiGetNum(volPath, "min");
    var volMax = apiGetNum(volPath, "max");
    var actualValue = volMin + volume * (volMax - volMin);

    var vol = new LiveAPI(volPath);
    vol.set("value", actualValue);

    return {
        track_name: apiGetStr(trackPath, "name"),
        volume: apiGetNum(volPath, "value"),
        normalized_volume: volume
    };
}

function cmd_set_track_panning(params) {
    var trackIndex = param(params, "track_index", 0);
    var panning = param(params, "panning", 0.0);
    if (panning < 0.0 || panning > 1.0) throw "Panning must be between 0.0 and 1.0";

    var trackPath = getTrackPath(trackIndex);
    var panPath = trackPath + " mixer_device panning";
    var panMin = apiGetNum(panPath, "min");
    var panMax = apiGetNum(panPath, "max");
    var actualValue = panMin + panning * (panMax - panMin);

    var pan = new LiveAPI(panPath);
    pan.set("value", actualValue);

    return {
        track_name: apiGetStr(trackPath, "name"),
        panning: apiGetNum(panPath, "value"),
        normalized_panning: panning
    };
}

function cmd_set_track_mute(params) {
    var trackIndex = param(params, "track_index", 0);
    var mute = param(params, "mute", false);
    var trackPath = getTrackPath(trackIndex);
    var track = new LiveAPI(trackPath);
    track.set("mute", mute ? 1 : 0);
    return {
        track_name: apiGetStr(trackPath, "name"),
        mute: apiGetNum(trackPath, "mute") ? true : false
    };
}

function cmd_set_track_solo(params) {
    var trackIndex = param(params, "track_index", 0);
    var solo = param(params, "solo", false);
    var trackPath = getTrackPath(trackIndex);
    var track = new LiveAPI(trackPath);
    track.set("solo", solo ? 1 : 0);
    return {
        track_name: apiGetStr(trackPath, "name"),
        solo: apiGetNum(trackPath, "solo") ? true : false
    };
}

function cmd_set_track_arm(params) {
    var trackIndex = param(params, "track_index", 0);
    var arm = param(params, "arm", false);
    var trackPath = "live_set tracks " + trackIndex;
    var canArm = apiGetNum(trackPath, "can_be_armed");
    if (!canArm) throw "Track cannot be armed";
    var track = new LiveAPI(trackPath);
    track.set("arm", arm ? 1 : 0);
    return {
        track_index: trackIndex,
        track_name: apiGetStr(trackPath, "name"),
        arm: apiGetNum(trackPath, "arm") ? true : false
    };
}

function cmd_set_send_level(params) {
    var trackIndex = param(params, "track_index", 0);
    var sendIndex = param(params, "send_index", 0);
    var value = param(params, "value", 0.0);
    var trackPath = getTrackPath(trackIndex);
    var sendPath = trackPath + " mixer_device sends " + sendIndex;

    var sendApi = new LiveAPI(sendPath);
    if (!sendApi.id || sendApi.id === "0") throw "Send index out of range";

    var sMin = apiGetNum(sendPath, "min");
    var sMax = apiGetNum(sendPath, "max");
    var actualValue = Math.max(sMin, Math.min(sMax, sMin + value * (sMax - sMin)));
    sendApi.set("value", actualValue);

    return {
        track_index: trackIndex,
        send_index: sendIndex,
        value: value,
        actual_value: apiGetNum(sendPath, "value")
    };
}

function cmd_start_playback() {
    var song = new LiveAPI("live_set");
    song.call("start_playing");
    return { playing: apiGetNum("live_set", "is_playing") ? true : false };
}

function cmd_stop_playback() {
    var song = new LiveAPI("live_set");
    song.call("stop_playing");
    return { playing: apiGetNum("live_set", "is_playing") ? true : false };
}

function cmd_play_arrangement(params) {
    var time = param(params, "time", null);
    var song = new LiveAPI("live_set");
    song.call("stop_all_clips");
    song.set("back_to_arranger", 1);
    if (time !== null) {
        song.set("current_song_time", Number(time));
    }
    song.call("start_playing");
    return {
        playing: true,
        position: apiGetNum("live_set", "current_song_time")
    };
}

function cmd_set_song_time(params) {
    var time = param(params, "time", 0.0);
    var target = Math.max(0.0, time);
    var song = new LiveAPI("live_set");
    for (var attempt = 0; attempt < 5; attempt++) {
        song.set("current_song_time", target);
        var actual = apiGetNum("live_set", "current_song_time");
        if (Math.abs(actual - target) < 0.5) break;
    }
    return { current_song_time: apiGetNum("live_set", "current_song_time") };
}

function cmd_set_record_mode(params) {
    var on = param(params, "on", false);
    var song = new LiveAPI("live_set");
    song.set("record_mode", on ? 1 : 0);
    return { record_mode: apiGetNum("live_set", "record_mode") ? true : false };
}

function cmd_set_arrangement_overdub(params) {
    var on = param(params, "on", false);
    var song = new LiveAPI("live_set");
    song.set("arrangement_overdub", on ? 1 : 0);
    return { arrangement_overdub: apiGetNum("live_set", "arrangement_overdub") ? true : false };
}

function cmd_set_back_to_arranger() {
    var song = new LiveAPI("live_set");
    song.set("back_to_arranger", 1);
    return { back_to_arranger: true };
}

function cmd_set_arrangement_loop(params) {
    var on = param(params, "on", true);
    var start = param(params, "start", null);
    var length = param(params, "length", null);
    var song = new LiveAPI("live_set");
    song.set("loop", on ? 1 : 0);
    if (start !== null) song.set("loop_start", Math.max(0.0, start));
    if (length !== null) song.set("loop_length", Math.max(0.0, length));
    return {
        loop: apiGetNum("live_set", "loop") ? true : false,
        loop_start: apiGetNum("live_set", "loop_start"),
        loop_length: apiGetNum("live_set", "loop_length")
    };
}

function cmd_undo() {
    var song = new LiveAPI("live_set");
    song.call("undo");
    return { undone: true };
}

function cmd_redo() {
    var song = new LiveAPI("live_set");
    song.call("redo");
    return { redone: true };
}

// ─── Track/Scene/Clip Management ───

function cmd_create_midi_track(params) {
    var index = param(params, "index", -1);
    var song = new LiveAPI("live_set");
    song.call("create_midi_track", index);
    var trackCount = apiGetCount("live_set", "tracks");
    var newIndex = (index === -1) ? trackCount - 1 : index;
    return {
        index: newIndex,
        name: apiGetStr("live_set tracks " + newIndex, "name")
    };
}

function cmd_create_audio_track(params) {
    var index = param(params, "index", -1);
    var song = new LiveAPI("live_set");
    var trackCount = apiGetCount("live_set", "tracks");
    if (index < 0) index = trackCount;
    song.call("create_audio_track", index);
    return {
        index: index,
        name: apiGetStr("live_set tracks " + index, "name"),
        track_count: apiGetCount("live_set", "tracks")
    };
}

function cmd_delete_track(params) {
    var trackIndex = param(params, "track_index", 0);
    var trackName = apiGetStr("live_set tracks " + trackIndex, "name");
    var song = new LiveAPI("live_set");
    song.call("delete_track", trackIndex);
    return {
        deleted_track: trackName,
        track_count: apiGetCount("live_set", "tracks")
    };
}

function cmd_duplicate_track(params) {
    var trackIndex = param(params, "track_index", 0);
    var trackName = apiGetStr("live_set tracks " + trackIndex, "name");
    var song = new LiveAPI("live_set");
    song.call("duplicate_track", trackIndex);
    return {
        original_track: trackName,
        new_track_index: trackIndex + 1,
        new_track_name: apiGetStr("live_set tracks " + (trackIndex + 1), "name"),
        track_count: apiGetCount("live_set", "tracks")
    };
}

function cmd_create_scene(params) {
    var index = param(params, "index", -1);
    var song = new LiveAPI("live_set");
    var sceneCount = apiGetCount("live_set", "scenes");
    if (index < 0) index = sceneCount;
    song.call("create_scene", index);
    return {
        scene_index: index,
        scene_count: apiGetCount("live_set", "scenes")
    };
}

function cmd_delete_scene(params) {
    var sceneIndex = param(params, "scene_index", 0);
    var sceneName = apiGetStr("live_set scenes " + sceneIndex, "name");
    var song = new LiveAPI("live_set");
    song.call("delete_scene", sceneIndex);
    return {
        deleted_scene: sceneName,
        scene_count: apiGetCount("live_set", "scenes")
    };
}

function cmd_set_scene_name(params) {
    var sceneIndex = param(params, "scene_index", 0);
    var name = param(params, "name", "");
    var scene = new LiveAPI("live_set scenes " + sceneIndex);
    scene.set("name", name);
    return {
        scene_index: sceneIndex,
        name: apiGetStr("live_set scenes " + sceneIndex, "name")
    };
}

function cmd_fire_scene(params) {
    var sceneIndex = param(params, "scene_index", 0);
    var scenePath = "live_set scenes " + sceneIndex;
    var scene = new LiveAPI(scenePath);
    if (!scene.id || scene.id === "0") throw "Scene index out of range";
    scene.call("fire");
    return {
        scene_index: sceneIndex,
        scene_name: apiGetStr(scenePath, "name"),
        fired: true
    };
}

function cmd_create_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var length = param(params, "length", 4.0);
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;

    var hasClip = apiGetNum(slotPath, "has_clip");
    if (hasClip) throw "Clip slot already has a clip";

    var slot = new LiveAPI(slotPath);
    slot.call("create_clip", length);

    var clipPath = slotPath + " clip";
    return {
        name: apiGetStr(clipPath, "name"),
        length: apiGetNum(clipPath, "length")
    };
}

function cmd_create_audio_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var filePath = param(params, "file_path", "");
    var trackPath = "live_set tracks " + trackIndex;

    var hasAudio = apiGetNum(trackPath, "has_audio_input");
    if (!hasAudio) throw "Track " + trackIndex + " is not an audio track";

    var slotPath = trackPath + " clip_slots " + clipIndex;
    var hasClip = apiGetNum(slotPath, "has_clip");
    if (hasClip) throw "Clip slot already has a clip";

    var slot = new LiveAPI(slotPath);
    slot.call("create_clip", filePath);

    var clipPath = slotPath + " clip";
    return {
        name: apiGetStr(clipPath, "name"),
        length: apiGetNum(clipPath, "length"),
        file_path: filePath,
        track_index: trackIndex,
        clip_index: clipIndex
    };
}

function cmd_delete_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var slotPath = trackPath + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot " + clipIndex;

    var trackName = apiGetStr(trackPath, "name");
    var slot = new LiveAPI(slotPath);
    slot.call("delete_clip");

    return {
        track_name: trackName,
        clip_index: clipIndex,
        deleted: true
    };
}

function cmd_duplicate_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var targetIndex = param(params, "target_index", -1);
    var trackPath = getTrackPath(trackIndex);
    var slotPath = trackPath + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in source slot " + clipIndex;

    var slotCount = apiGetCount(trackPath, "clip_slots");
    if (targetIndex < 0) {
        targetIndex = -1;
        for (var i = 0; i < slotCount; i++) {
            if (!apiGetNum(trackPath + " clip_slots " + i, "has_clip")) {
                targetIndex = i;
                break;
            }
        }
        if (targetIndex < 0) throw "No empty clip slots available";
    }

    if (apiGetNum(trackPath + " clip_slots " + targetIndex, "has_clip")) {
        throw "Target slot " + targetIndex + " already has a clip";
    }

    var slot = new LiveAPI(slotPath);
    var targetSlot = new LiveAPI(trackPath + " clip_slots " + targetIndex);
    slot.call("duplicate_clip_to", targetSlot.id);

    return {
        track_name: apiGetStr(trackPath, "name"),
        source_index: clipIndex,
        target_index: targetIndex,
        duplicated: true
    };
}

function cmd_set_clip_name(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var name = param(params, "name", "");
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var clip = new LiveAPI(clipPath);
    clip.set("name", name);
    return { name: apiGetStr(clipPath, "name") };
}

function cmd_set_clip_loop(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var loopStart = param(params, "loop_start", null);
    var loopEnd = param(params, "loop_end", null);
    var looping = param(params, "looping", null);
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var clip = new LiveAPI(clipPath);

    if (looping !== null) clip.set("looping", looping ? 1 : 0);
    if (loopStart !== null) clip.set("loop_start", Number(loopStart));
    if (loopEnd !== null) clip.set("loop_end", Number(loopEnd));

    return {
        looping: apiGetNum(clipPath, "looping") ? true : false,
        loop_start: apiGetNum(clipPath, "loop_start"),
        loop_end: apiGetNum(clipPath, "loop_end"),
        length: apiGetNum(clipPath, "length")
    };
}

function cmd_fire_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var slot = new LiveAPI(slotPath);
    slot.call("fire");
    return { fired: true };
}

function cmd_stop_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;
    var slot = new LiveAPI(slotPath);
    slot.call("stop");
    return { stopped: true };
}

function cmd_add_notes_to_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var notes = param(params, "notes", []);
    var slotPath = "live_set tracks " + trackIndex + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var clip = new LiveAPI(clipPath);

    if (!apiGetNum(clipPath, "is_midi_clip")) throw "Not a MIDI clip";

    // Use set_notes protocol: call("notes", count), then per-note call("note", ...), then call("done")
    // CRITICAL: time and duration must be strings with decimal points to avoid "Invalid syntax" bug
    clip.call("set_notes");
    clip.call("notes", notes.length);
    for (var i = 0; i < notes.length; i++) {
        var n = notes[i];
        var pitch = n.pitch !== undefined ? Math.floor(n.pitch) : 60;
        var startTime = n.start_time !== undefined ? Number(n.start_time).toFixed(8) : "0.0";
        var duration = n.duration !== undefined ? Number(n.duration).toFixed(8) : "0.25";
        var velocity = n.velocity !== undefined ? Math.floor(n.velocity) : 100;
        var mute = n.mute ? 1 : 0;
        clip.call("note", pitch, startTime, duration, velocity, mute);
    }
    clip.call("done");

    return { note_count: notes.length };
}

// ─── Devices, Browser & Automation ───

function cmd_set_device_parameter(params) {
    var trackIndex = param(params, "track_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var parameterIndex = param(params, "parameter_index", 0);
    var value = param(params, "value", 0.0);
    var trackPath = getTrackPath(trackIndex);
    var pPath = trackPath + " devices " + deviceIndex + " parameters " + parameterIndex;

    var pApi = new LiveAPI(pPath);
    if (!pApi.id || pApi.id === "0") throw "Parameter index out of range";

    if (value < 0.0 || value > 1.0) throw "Normalized value must be between 0.0 and 1.0";

    var pMin = apiGetNum(pPath, "min");
    var pMax = apiGetNum(pPath, "max");
    var actualValue = pMin + value * (pMax - pMin);
    pApi.set("value", actualValue);

    return {
        parameter_name: apiGetStr(pPath, "name"),
        value: apiGetNum(pPath, "value"),
        normalized_value: value
    };
}

function cmd_batch_set_device_parameters(params) {
    var trackIndex = param(params, "track_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var parameterIndices = param(params, "parameter_indices", []);
    var values = param(params, "values", []);
    var trackPath = getTrackPath(trackIndex);
    var devPath = trackPath + " devices " + deviceIndex;

    if (parameterIndices.length !== values.length) throw "parameter_indices and values must have the same length";

    var updated = [];
    var paramCount = apiGetCount(devPath, "parameters");

    for (var i = 0; i < parameterIndices.length; i++) {
        var pIdx = parameterIndices[i];
        var val = values[i];
        if (pIdx < 0 || pIdx >= paramCount) continue;
        if (val < 0.0 || val > 1.0) continue;

        var pPath = devPath + " parameters " + pIdx;
        var pMin = apiGetNum(pPath, "min");
        var pMax = apiGetNum(pPath, "max");
        var actualVal = pMin + val * (pMax - pMin);
        var p = new LiveAPI(pPath);
        p.set("value", actualVal);

        updated.push({
            index: pIdx,
            name: apiGetStr(pPath, "name"),
            value: apiGetNum(pPath, "value"),
            normalized_value: val
        });
    }

    return {
        updated_count: updated.length,
        parameters: updated
    };
}

function cmd_delete_device(params) {
    var trackIndex = param(params, "track_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var trackPath = getTrackPath(trackIndex);
    var devPath = trackPath + " devices " + deviceIndex;

    var devName = apiGetStr(devPath, "name");
    var track = new LiveAPI(trackPath);
    track.call("delete_device", deviceIndex);

    return {
        deleted_device: devName,
        device_count: apiGetCount(trackPath, "devices")
    };
}

function cmd_load_instrument_or_effect(params) {
    throw "Browser/instrument loading is not accessible from Max for Live devices. Drag instruments manually from Ableton's browser, or use the Remote Script backend instead.";
}

function cmd_set_clip_envelope(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var parameterIndex = param(params, "parameter_index", 0);
    var points = param(params, "points", []);
    var trackPath = "live_set tracks " + trackIndex;
    var slotPath = trackPath + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var pPath = trackPath + " devices " + deviceIndex + " parameters " + parameterIndex;
    var pMin = apiGetNum(pPath, "min");
    var pMax = apiGetNum(pPath, "max");
    var paramName = apiGetStr(pPath, "name");

    var clip = new LiveAPI(clipPath);
    var paramApi = new LiveAPI(pPath);

    // Try to get or create envelope
    var envId = clip.call("automation_envelope", "id", paramApi.id);
    if (!envId || envId === "0" || envId === 0) {
        envId = clip.call("create_automation_envelope", "id", paramApi.id);
    }
    if (!envId || envId === "0" || envId === 0) {
        throw "Could not create automation envelope for parameter";
    }

    var env = new LiveAPI("id " + envId);

    // Sort points by time and interpolate
    var sorted = [];
    for (var i = 0; i < points.length; i++) {
        sorted.push({
            time: Number(points[i].time || 0),
            value: Number(points[i].value || 0)
        });
    }
    sorted.sort(function (a, b) { return a.time - b.time; });

    var stepSize = 0.25;
    for (var s = 0; s < sorted.length - 1; s++) {
        var t0 = sorted[s].time;
        var v0 = sorted[s].value;
        var t1 = sorted[s + 1].time;
        var v1 = sorted[s + 1].value;
        var segDur = t1 - t0;
        var numSteps = Math.max(1, Math.floor(segDur / stepSize));
        for (var st = 0; st < numSteps; st++) {
            var frac = st / numSteps;
            var t = t0 + frac * segDur;
            var v = v0 + frac * (v1 - v0);
            var actual = pMin + v * (pMax - pMin);
            env.call("insert_step", t, stepSize, actual);
        }
    }
    // Last point holds for 1 beat
    if (sorted.length > 0) {
        var last = sorted[sorted.length - 1];
        var lastActual = pMin + last.value * (pMax - pMin);
        env.call("insert_step", last.time, 1.0, lastActual);
    }

    return {
        track_index: trackIndex,
        clip_index: clipIndex,
        device_index: deviceIndex,
        parameter_index: parameterIndex,
        parameter_name: paramName,
        points_set: points.length
    };
}

function cmd_clear_clip_envelope(params) {
    var trackIndex = param(params, "track_index", 0);
    var clipIndex = param(params, "clip_index", 0);
    var deviceIndex = param(params, "device_index", 0);
    var parameterIndex = param(params, "parameter_index", 0);
    var trackPath = "live_set tracks " + trackIndex;
    var slotPath = trackPath + " clip_slots " + clipIndex;

    if (!apiGetNum(slotPath, "has_clip")) throw "No clip in slot";

    var clipPath = slotPath + " clip";
    var pPath = trackPath + " devices " + deviceIndex + " parameters " + parameterIndex;
    var paramName = apiGetStr(pPath, "name");

    var clip = new LiveAPI(clipPath);
    var paramApi = new LiveAPI(pPath);
    clip.call("clear_envelope", "id", paramApi.id);

    return {
        track_index: trackIndex,
        clip_index: clipIndex,
        parameter_name: paramName,
        cleared: true
    };
}

// ─── Ported from the Python Remote Script (routing, arrangement clips, record_arrangement) ───

// LiveAPI returns dictionary-valued properties (routing types, get_notes_extended) as a JSON
// string, usually wrapped as {"<prop>": ...}. Normalise to a plain JS value.
function apiGetJson(api, prop) {
    var raw = api.get(prop);
    if (raw instanceof Array) raw = raw.join(" ");
    raw = String(raw);
    var parsed;
    try {
        parsed = JSON.parse(raw);
    } catch (e) {
        throw "Could not parse " + prop + " as JSON: " + raw;
    }
    if (parsed && typeof parsed === "object" && parsed.hasOwnProperty(prop)) return parsed[prop];
    return parsed;
}

function parseCallJson(raw) {
    if (raw instanceof Array) raw = raw.join(" ");
    return JSON.parse(String(raw));
}

function routingName(r) {
    if (!r) return "";
    return r.display_name !== undefined ? String(r.display_name) : String(r);
}

function cmd_get_track_routing(params) {
    var trackIndex = param(params, "track_index", 0);
    var track = getTrack(trackIndex);
    if (!track.id || track.id === "0") throw "Track index out of range: " + trackIndex;

    var result = {
        input_routing_type: routingName(apiGetJson(track, "input_routing_type")),
        output_routing_type: routingName(apiGetJson(track, "output_routing_type"))
    };
    var avIn = apiGetJson(track, "available_input_routing_types") || [];
    var avOut = apiGetJson(track, "available_output_routing_types") || [];
    result.available_input_routing_types = [];
    result.available_output_routing_types = [];
    var i;
    for (i = 0; i < avIn.length; i++) result.available_input_routing_types.push({ display_name: routingName(avIn[i]) });
    for (i = 0; i < avOut.length; i++) result.available_output_routing_types.push({ display_name: routingName(avOut[i]) });
    return result;
}

function setRouting(trackIndex, prop, availableProp, wantedName, caseInsensitive) {
    var track = getTrack(trackIndex);
    if (!track.id || track.id === "0") throw "Track index out of range: " + trackIndex;

    var available = apiGetJson(track, availableProp) || [];
    var names = [];
    for (var i = 0; i < available.length; i++) {
        var name = routingName(available[i]);
        names.push(name);
        var match = caseInsensitive ? (name.toLowerCase() === String(wantedName).toLowerCase()) : (name === wantedName);
        if (match) {
            // Setting a routing takes the dictionary back (identifier is what Live keys on).
            track.set(prop, JSON.stringify({ display_name: name, identifier: available[i].identifier }));
            var now = routingName(apiGetJson(track, prop));
            if (now !== name) throw "Live did not accept routing " + name + " (still " + now + ")";
            return name;
        }
    }
    throw "Routing type not found: " + wantedName + ". Available: " + names.join(", ");
}

function cmd_set_track_input_routing(params) {
    var name = setRouting(param(params, "track_index", 0), "input_routing_type",
        "available_input_routing_types", param(params, "routing_type_name", ""), false);
    return { input_routing_type: name };
}

function cmd_set_track_output_routing(params) {
    var name = setRouting(param(params, "track_index", 0), "output_routing_type",
        "available_output_routing_types", param(params, "routing_type_name", ""), true);
    return { output_routing_type: name };
}

function cmd_set_track_monitoring(params) {
    var trackIndex = param(params, "track_index", 0);
    var state = Math.floor(param(params, "state", 1)); // 0=In, 1=Auto, 2=Off
    var track = getTrack(trackIndex);
    if (!track.id || track.id === "0") throw "Track index out of range: " + trackIndex;
    track.set("current_monitoring_state", state);
    return { monitoring_state: apiGetNum(getTrackPath(trackIndex), "current_monitoring_state") };
}

// Read every note in a clip via get_notes_extended (Live 11+), falling back to the
// select-all protocol used by cmd_get_clip_notes.
function readAllNotes(clip, clipLength) {
    try {
        var data = parseCallJson(clip.call("get_notes_extended", 0, 128, 0, clipLength));
        var notes = data.notes || [];
        var out = [];
        for (var i = 0; i < notes.length; i++) {
            out.push({
                pitch: Number(notes[i].pitch),
                start_time: Number(notes[i].start_time),
                duration: Number(notes[i].duration),
                velocity: Number(notes[i].velocity),
                mute: notes[i].mute ? true : false
            });
        }
        return out;
    } catch (e) {
        post("get_notes_extended failed (" + e + "), falling back to get_selected_notes\n");
    }
    clip.call("select_all_notes");
    var rawNotes = clip.call("get_selected_notes");
    var list = [];
    if (rawNotes && rawNotes.length > 2) {
        var count = Number(rawNotes[1]);
        var idx = 2;
        for (var n = 0; n < count; n++) {
            if (idx + 5 > rawNotes.length) break;
            list.push({
                pitch: Number(rawNotes[idx + 1]),
                start_time: Number(rawNotes[idx + 2]),
                duration: Number(rawNotes[idx + 3]),
                velocity: Number(rawNotes[idx + 4]),
                mute: Number(rawNotes[idx + 5]) ? true : false
            });
            idx += 6;
        }
    }
    clip.call("deselect_all_notes");
    return list;
}

// Write notes with the set_notes protocol. Time/duration MUST be decimal strings (see troubleshooting #7).
function writeNotes(clip, notes) {
    clip.call("set_notes");
    clip.call("notes", notes.length);
    for (var i = 0; i < notes.length; i++) {
        var n = notes[i];
        var pitch = n.pitch !== undefined ? Math.floor(n.pitch) : 60;
        var startTime = n.start_time !== undefined ? Number(n.start_time).toFixed(8) : "0.0";
        var duration = n.duration !== undefined ? Number(n.duration).toFixed(8) : "0.25";
        var velocity = n.velocity !== undefined ? Math.floor(n.velocity) : 100;
        var mute = n.mute ? 1 : 0;
        clip.call("note", pitch, startTime, duration, velocity, mute);
    }
    clip.call("done");
    return notes.length;
}

function getArrangementClip(trackIndex, arrangementClipIndex) {
    var trackPath = "live_set tracks " + trackIndex;
    var count = apiGetCount(trackPath, "arrangement_clips");
    if (arrangementClipIndex < 0 || arrangementClipIndex >= count) {
        throw "Arrangement clip index out of range (track has " + count + " arrangement clips)";
    }
    return new LiveAPI(trackPath + " arrangement_clips " + arrangementClipIndex);
}

function cmd_get_arrangement_clip_notes(params) {
    var trackIndex = param(params, "track_index", 0);
    var idx = param(params, "arrangement_clip_index", 0);
    var clip = getArrangementClip(trackIndex, idx);
    if (!apiGetNum(clip.unquotedpath, "is_midi_clip")) throw "Not a MIDI clip";

    var clipLength = apiGetNum(clip.unquotedpath, "length");
    var notes = readAllNotes(clip, clipLength);
    return {
        track_index: trackIndex,
        arrangement_clip_index: idx,
        clip_name: apiGetStr(clip.unquotedpath, "name"),
        start_time: apiGetNum(clip.unquotedpath, "start_time"),
        length: clipLength,
        note_count: notes.length,
        notes: notes
    };
}

function cmd_delete_arrangement_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var idx = param(params, "arrangement_clip_index", 0);
    var trackPath = "live_set tracks " + trackIndex;
    var clip = getArrangementClip(trackIndex, idx);
    var before = apiGetCount(trackPath, "arrangement_clips");

    var track = new LiveAPI(trackPath);
    track.call("delete_clip", "id " + clip.id);

    var after = apiGetCount(trackPath, "arrangement_clips");
    if (after !== before - 1) throw "delete_clip did not remove the clip (count " + before + " -> " + after + ")";
    return { track_index: trackIndex, deleted_index: idx, remaining_count: after };
}

function findArrangementClipIndex(trackPath, startTime) {
    var count = apiGetCount(trackPath, "arrangement_clips");
    for (var i = 0; i < count; i++) {
        if (Math.abs(apiGetNum(trackPath + " arrangement_clips " + i, "start_time") - startTime) < 0.001) return i;
    }
    return -1;
}

function cmd_create_arrangement_midi_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var start = Number(param(params, "time", 0.0));
    var length = Number(param(params, "length", 4.0));
    var notes = param(params, "notes", null);
    var trackPath = "live_set tracks " + trackIndex;

    if (trackIndex < 0 || trackIndex >= apiGetCount("live_set", "tracks")) throw "Track index out of range";
    if (!apiGetNum(trackPath, "has_midi_input")) throw "Track " + trackIndex + " is not a MIDI track";

    var track = new LiveAPI(trackPath);
    // Live 11+: Track.create_midi_clip(start_time, length) in beats
    track.call("create_midi_clip", start.toFixed(8), length.toFixed(8));

    var idx = findArrangementClipIndex(trackPath, start);
    if (idx < 0) throw "create_midi_clip did not produce a clip at " + start;
    var clip = new LiveAPI(trackPath + " arrangement_clips " + idx);

    var noteCount = 0;
    if (notes && notes.length) noteCount = writeNotes(clip, notes);

    return {
        track_index: trackIndex,
        start_time: start,
        length: apiGetNum(clip.unquotedpath, "length"),
        note_count: noteCount,
        arrangement_clip_index: idx,
        name: apiGetStr(clip.unquotedpath, "name")
    };
}

function cmd_create_arrangement_audio_clip(params) {
    var trackIndex = param(params, "track_index", 0);
    var filePath = param(params, "file_path", "");
    var start = Number(param(params, "time", 0.0));
    var length = param(params, "length", null);
    var trackPath = "live_set tracks " + trackIndex;

    if (trackIndex < 0 || trackIndex >= apiGetCount("live_set", "tracks")) throw "Track index out of range";
    if (!apiGetNum(trackPath, "has_audio_input")) throw "Track " + trackIndex + " is not an audio track";

    var track = new LiveAPI(trackPath);
    // Live 11+: Track.create_audio_clip(file_path, position)
    track.call("create_audio_clip", filePath, start.toFixed(8));

    var idx = findArrangementClipIndex(trackPath, start);
    if (idx < 0) throw "create_audio_clip did not produce a clip at " + start + " (bad file path?)";
    var clip = new LiveAPI(trackPath + " arrangement_clips " + idx);

    // `length` is accepted for parity with the Remote Script but neither backend can trim an
    // arrangement audio clip: end_time is read-only and end_marker does not change the
    // arrangement span. The clip takes the sample's full length; end_time below is the truth.

    return {
        track_index: trackIndex,
        file_path: filePath,
        start_time: start,
        end_time: apiGetNum(clip.unquotedpath, "end_time"),
        length: apiGetNum(clip.unquotedpath, "length"),
        name: apiGetStr(clip.unquotedpath, "name"),
        arrangement_clip_index: idx
    };
}

// record_arrangement: fire scenes in sequence while Live records session -> arrangement.
// Same strategy as the Remote Script: 1-bar clip trigger quantization, fire the next scene
// two beats before the section boundary, poll current_song_time with a Task.
function cmd_record_arrangement(params) {
    var sections = param(params, "sections", []);
    var startTime = Number(param(params, "start_time", 0.0));
    if (!sections.length) throw "No sections given";

    return deferred(function (resolve, reject) {
        var song = new LiveAPI("live_set");
        var tempo = apiGetNum("live_set", "tempo");
        var beatsPerBar = apiGetNum("live_set", "signature_numerator");
        var sceneCount = apiGetCount("live_set", "scenes");
        var savedQuant = apiGetNum("live_set", "clip_trigger_quantization");

        var state = {
            i: -1, totalBars: 0, recorded: [], targetBeat: 0, fireBeat: null, nextFired: false, pollTask: null
        };

        function fireScene(idx) {
            var scene = new LiveAPI("live_set scenes " + idx);
            scene.call("fire");
            return apiGetStr("live_set scenes " + idx, "name");
        }

        function cleanup(ok) {
            try { if (state.pollTask) state.pollTask.cancel(); } catch (e) {}
            try { song.set("record_mode", 0); } catch (e) {}
            try { song.call("stop_playing"); } catch (e) {}
            try { song.set("clip_trigger_quantization", savedQuant); } catch (e) {}
            if (ok) {
                try { song.call("stop_all_clips"); } catch (e) {}
                try { song.set("back_to_arranger", 1); } catch (e) {}
                try { song.set("current_song_time", 0); } catch (e) {}
            }
        }

        function nextSection() {
            state.i++;
            while (state.i < sections.length) {
                var si = Math.floor(sections[state.i].scene_index || 0);
                if (si >= 0 && si < sceneCount) break;
                post("record_arrangement: skipping invalid scene index " + si + "\n");
                state.i++;
            }
            if (state.i >= sections.length) {
                cleanup(true);
                resolve({
                    total_bars: state.totalBars,
                    total_beats: state.totalBars * beatsPerBar,
                    sections: state.recorded,
                    tempo: tempo
                });
                return;
            }

            var sec = sections[state.i];
            var sceneIdx = Math.floor(sec.scene_index || 0);
            var bars = Math.floor(sec.bars || 8);
            var sceneName = (state.i === 0 || !state.nextFired)
                ? fireScene(sceneIdx)
                : apiGetStr("live_set scenes " + sceneIdx, "name");

            state.targetBeat = startTime + (state.totalBars + bars) * beatsPerBar;
            state.nextFired = false;
            state.fireBeat = null;
            // Look ahead for the next valid section so we can pre-fire it
            for (var j = state.i + 1; j < sections.length; j++) {
                var nsi = Math.floor(sections[j].scene_index || 0);
                if (nsi >= 0 && nsi < sceneCount) { state.fireBeat = state.targetBeat - 2.0; state.nextSceneIdx = nsi; break; }
            }

            state.recorded.push({
                scene_index: sceneIdx, scene_name: sceneName, bars: bars,
                start_bar: state.totalBars + 1, end_bar: state.totalBars + bars
            });
            state.totalBars += bars;
            post("record_arrangement: section " + (state.i + 1) + " scene " + sceneIdx + " (" + sceneName + ") for " + bars + " bars\n");
        }

        function poll() {
            try {
                var current = apiGetNum("live_set", "current_song_time");
                if (state.fireBeat !== null && !state.nextFired && current >= state.fireBeat) {
                    fireScene(state.nextSceneIdx);
                    state.nextFired = true;
                }
                if (current >= state.targetBeat - 0.5) {
                    nextSection();
                    if (state.i >= sections.length) return; // resolved in nextSection
                }
                state.pollTask = new Task(poll);
                state.pollTask.schedule(20);
            } catch (e) {
                cleanup(false);
                reject(e);
            }
        }

        try {
            song.set("clip_trigger_quantization", 4); // 1 Bar
            var trackCount = apiGetCount("live_set", "tracks");
            for (var t = 0; t < trackCount; t++) {
                var tp = "live_set tracks " + t;
                if (apiGetNum(tp, "can_be_armed") && apiGetNum(tp, "arm")) new LiveAPI(tp).set("arm", 0);
            }
            if (apiGetNum("live_set", "is_playing")) song.call("stop_playing");
            song.set("back_to_arranger", 1);
            song.set("current_song_time", startTime);
            song.set("record_mode", 1);
            nextSection();
            state.pollTask = new Task(poll);
            state.pollTask.schedule(20);
        } catch (e) {
            cleanup(false);
            reject(e);
        }
    });
}
