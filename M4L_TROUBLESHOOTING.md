# Max for Live Device — Troubleshooting & Known Issues

Problems encountered during M4L device development, roughly ordered by how much time they wasted.

## 1. node.script Caches JS Files for the Entire Ableton Session

**Symptom**: You update `tcp-server.js` or `lom-handler.js`, copy to User Library, remove and re-drag the device — but old code still runs.

**Cause**: `node.script` caches loaded JS files and does not re-read them when the device is reloaded.

**Fix**: Fully quit Ableton (Cmd+Q) and reopen. There is no way to force a reload without restarting.

**Impact**: Every code change requires a full Ableton restart. This makes iterative debugging extremely painful — each fix/test cycle takes 30-60 seconds.

## 2. Browser API Does Not Exist in M4L

**Symptom**: Browser-related commands fail with `"component 'browser' is not an object"` or `"'Application' object has no attribute 'browser'"`.

**What was tried** (all failed):
- `new LiveAPI("live_app browser instruments")` — "component 'browser' is not an object"
- `new LiveAPI("live_app browser children 0")` — "component 'instruments' is not an object"
- `var app = new LiveAPI("live_app"); app.get("browser")` — "'Application' object has no attribute 'browser'"
- ID-based lookup after getting browser ID — same errors

**Root cause**: The `Application.browser` property is only available from Python Remote Scripts running inside Ableton's built-in Python interpreter. It is not part of the LOM exposed to Max for Live.

**Fix**: Browser commands return clear error messages telling users to drag instruments manually or use the Remote Script backend.

## 3. .amxd File Requires Binary Header

**Symptom**: File appears in Ableton's browser but cannot be dragged onto a track (cursor shows "not allowed").

**Cause**: `.amxd` files are not plain JSON. They need a 32-byte binary header (see DEVELOPMENT.md for format).

**Fix**: Use `build_amxd.py` to generate the file. Never hand-edit the `.amxd` directly.

## 4. JS Files Must Be Flat Next to .amxd

**Symptom**: `node.script` or `js` object fails to find its script file. Max console shows file-not-found errors.

**What was tried**: Putting JS files in a `code/` subfolder and using `searchpath` in the project JSON.

**Fix**: Copy all JS files flat next to the `.amxd` in the User Library. Subfolder path resolution doesn't work for unfrozen devices.

**Gotcha**: If you previously deployed with a `code/` subfolder, the old files may linger and confuse things. Delete the old subfolder explicitly.

## 5. Dict-Based IPC Is Race-Prone

**Symptom**: Commands intermittently return wrong results or stale data.

**Cause**: `maxAPI.setDict()` is async — the dict may not be written by the time the trigger message arrives.

**Fix**: Pass JSON strings directly as Max messages instead of using named dicts.

## 6. `route` Object Strips Selectors

**Symptom**: `js` object receives bare `bang` instead of the response message with requestId and data.

**Cause**: Max's `route` object matches and strips the first argument (the selector), forwarding only the remaining arguments. When a response message like `response 123 {...}` goes through `route response`, the `js` only sees `123 {...}`.

**Fix**: Wire messages directly between `node.script` and `js` outlets/inlets without `route`. Use `function command()` / `function response()` as named message handlers in the `js` object.

## 7. set_notes Requires Decimal Values

**Symptom**: `call("note", ...)` throws "Invalid syntax" for notes with integer time or duration.

**Cause**: The M4L `call("note", pitch, time, duration, velocity, mute)` API expects float strings, not integers. `1` fails but `1.00000000` works.

**Fix**: Always use `.toFixed(8)` on time and duration values before passing to `call("note", ...)`.

## 8. Audio Clips Are Not Editable

**Symptom**: `get_clip_notes` returns "Not a MIDI clip" for audio clips.

**Cause**: The LOM does not expose audio clip warp markers or transients. `get_clip_notes` and `add_notes_to_clip` only work on MIDI clips.

**Workaround**: Mute the audio track, create a new MIDI track with the appropriate instrument loaded, and program a MIDI replacement clip.

## 9. Drum Rack Pitch Mapping

**Symptom**: Notes are added to a clip with a Drum Rack but no sound plays.

**Cause**: Drum racks map sounds to specific pitches (e.g., 808 Core Kit kick = pitch 36/C1). Using pitch 60/C4 (the default for DS instruments) produces silence because no pad is mapped there.

**Fix**: Always check the drum rack's pad layout before programming notes. Common mappings: kick = 36 (C1), snare = 38 (D1), closed hi-hat = 42 (F#1).

## 10. Session State Lost on Restart

**Symptom**: After restarting Ableton to pick up code changes, all tracks and clips from the previous session are gone.

**Cause**: If the Live Set wasn't saved, Ableton opens a fresh default set on restart.

**Impact**: When iterating on M4L code, you lose your test project every restart unless you save first. Combined with issue #1 (caching), this creates a brutal development loop.

**Mitigation**: Save the Live Set before every restart. Consider keeping a template project for testing.

## 11. Deployed Files May Not Actually Update

**Symptom**: `cp` command reports success but the deployed file hasn't changed (verified by checking file size or content).

**Cause**: macOS file system caching or app bundle protection quirks. Similar to the Remote Script `cp` issue.

**Fix**: Use explicit `rm` before `cp`, and verify with `wc -l` or `md5` after copying.

## 12. Arrangement Commands May Timeout

**Symptom**: `get_full_arrangement` and `get_arrangement_info` fail with connection errors.

**Cause**: Likely due to the amount of data being serialized or node.script TCP buffer limits.

**Workaround**: Works more reliably with smaller projects. Use `get_session_info` as an alternative for basic track/clip info.

## 13. Python Remote Script Cannot Run Inside M4L

**Investigated**: Whether the existing Python Remote Script could be embedded in the M4L device to get browser access and full functionality.

**Result**: Not possible. The Remote Script depends on Ableton's internal Python API (`ControlSurface`, `Song`, etc.) which is only available in Ableton's built-in Python interpreter. M4L's `js` object runs SpiderMonkey (ES5), and `node.script` runs Node.js — neither has access to Ableton's Python runtime.
