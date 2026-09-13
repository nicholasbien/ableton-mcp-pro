#!/usr/bin/env python3
"""Build a valid .amxd file with the required binary header."""
import json
import struct
import os
import time

DEVICE_TYPE_AUDIO_EFFECT = 0x61616161  # 'aaaa'

# TCP port the device listens on. 9878 by default so it can coexist with the
# Python Remote Script (9877). Point the MCP server at it with ABLETON_PORT=9878.
PORT = 9878

patcher = {
    "patcher": {
        "fileversion": 1,
        "appversion": {
            "major": 8,
            "minor": 6,
            "revision": 5,
            "architecture": "x64",
            "modernui": 1
        },
        "classnamespace": "box",
        "rect": [100.0, 100.0, 640.0, 480.0],
        "bglocked": 0,
        "openinpresentation": 1,
        "default_fontsize": 12.0,
        "default_fontface": 0,
        "default_fontname": "Arial",
        "gridonopen": 1,
        "gridsize": [15.0, 15.0],
        "gridsnaponopen": 1,
        "objectsnaponopen": 1,
        "statusbarvisible": 2,
        "toolbarvisible": 1,
        "lefttoolbarpinned": 0,
        "tede": 0,
        "default_maxclass": "",
        "default_object_width": 128,
        "description": "",
        "digest": "",
        "tags": "",
        "style": "",
        "subpatcher_template": "",
        "devicewidth": 246,
        "autosave": 0,
        "boxes": [
            {
                "box": {
                    "id": "obj-1",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [250.0, 30.0, 120.0, 22.0],
                    "text": "loadmess script start"
                }
            },
            {
                "box": {
                    "id": "obj-2",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [30.0, 30.0, 190.0, 22.0],
                    "text": "node.script tcp-server.js " + str(PORT)
                }
            },
            {
                "box": {
                    "id": "obj-3",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": [""],
                    "patching_rect": [30.0, 70.0, 170.0, 22.0],
                    "text": "js lom-handler.js"
                }
            },
            {
                "box": {
                    "id": "obj-7",
                    "maxclass": "comment",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [30.0, 120.0, 220.0, 20.0],
                    "presentation": 1,
                    "presentation_rect": [10.0, 10.0, 226.0, 20.0],
                    "text": "AbletonMCP — TCP:" + str(PORT)
                }
            },
            {
                "box": {
                    "id": "obj-10",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 1,
                    "outlettype": ["signal"],
                    "patching_rect": [420.0, 30.0, 70.0, 22.0],
                    "text": "plugin~"
                }
            },
            {
                "box": {
                    "id": "obj-11",
                    "maxclass": "newobj",
                    "numinlets": 1,
                    "numoutlets": 0,
                    "patching_rect": [420.0, 70.0, 80.0, 22.0],
                    "text": "plugout~"
                }
            }
        ],
        "lines": [
            {
                "patchline": {
                    "source": ["obj-1", 0],
                    "destination": ["obj-2", 0]
                }
            },
            {
                "patchline": {
                    "source": ["obj-2", 0],
                    "destination": ["obj-3", 0]
                }
            },
            {
                "patchline": {
                    "source": ["obj-3", 0],
                    "destination": ["obj-2", 0]
                }
            },
            {
                "patchline": {
                    "source": ["obj-10", 0],
                    "destination": ["obj-11", 0]
                }
            }
        ],
        "project": {
            "version": 1,
            "creationdate": int(time.time()),
            "modificationdate": int(time.time()),
            "viewrect": [0.0, 0.0, 300.0, 500.0],
            "autoorganize": 1,
            "hideprojectwindow": 1,
            "showdependencies": 1,
            "autolocalize": 0,
            "contents": {
                "patchers": {},
                "code": {}
            },
            "layout": {},
            "searchpath": {
                "code": {
                    "relative": 1,
                    "auditfolder": 1,
                    "noedit": 1
                }
            },
            "detailsvisible": 0,
            "amxdtype": DEVICE_TYPE_AUDIO_EFFECT,
            "readonly": 0,
            "devpathtype": 0,
            "devpath": ".",
            "sortmode": 0,
            "viewmode": 0
        },
        "dependency_cache": [
            {"name": "tcp-server.js", "bootpath": ".", "type": "TEXT", "implicit": 1},
            {"name": "lom-handler.js", "bootpath": ".", "type": "TEXT", "implicit": 1}
        ]
    }
}

def build_amxd(output_path, device_type, patcher_dict):
    json_bytes = json.dumps(patcher_dict, indent='\t').encode('utf-8')
    # JSON data + null terminator
    ptch_size = len(json_bytes) + 1

    header = b''
    header += b'ampf'                                    # magic
    header += struct.pack('<I', 4)                       # size of device type field
    header += struct.pack('<I', device_type)             # device type
    header += b'meta'                                    # meta marker
    header += struct.pack('<I', 4)                       # meta size
    header += struct.pack('<I', 0)                       # meta content (unfrozen)
    header += b'ptch'                                    # patch marker
    header += struct.pack('<I', ptch_size)               # patch size

    with open(output_path, 'wb') as f:
        f.write(header)
        f.write(json_bytes)
        f.write(b'\x00')

    print(f"Built {output_path} ({len(header) + len(json_bytes) + 1} bytes)")

if __name__ == '__main__':
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output = os.path.join(script_dir, 'AbletonMCP.amxd')
    build_amxd(output, DEVICE_TYPE_AUDIO_EFFECT, patcher)
