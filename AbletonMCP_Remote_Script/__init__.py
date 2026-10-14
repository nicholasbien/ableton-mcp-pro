# AbletonMCP/init.py
from __future__ import absolute_import, print_function, unicode_literals

from _Framework.ControlSurface import ControlSurface
import socket
import json
import threading
import time
import traceback

# Change queue import for Python 2
try:
    import Queue as queue  # Python 2
except ImportError:
    import queue  # Python 3

# Constants for socket communication
DEFAULT_PORT = 9877
HOST = "localhost"
EVENT_BUFFER_SIZE = 1000

# Commands that change Live's state; they run on Live's main thread via schedule_message
MODIFYING_COMMANDS = frozenset([
    "create_midi_track", "set_track_name", "create_clip", "create_arrangement_audio_clip",
    "create_arrangement_audio_clips_batch", "create_arrangement_midi_clip", "delete_arrangement_clip", "add_notes_to_clip",
    "set_clip_name", "set_tempo", "fire_clip", "stop_clip",
    "start_playback", "stop_playback", "play_arrangement", "load_browser_item",
    "load_instrument_or_effect", "set_device_parameter", "batch_set_device_parameters", "set_track_volume",
    "set_track_panning", "fire_scene", "set_song_time", "set_record_mode",
    "set_arrangement_overdub", "set_back_to_arranger", "set_arrangement_loop", "set_track_mute",
    "set_track_solo", "delete_clip", "duplicate_clip", "create_scene",
    "delete_scene", "set_scene_name", "create_audio_track", "delete_track",
    "delete_device", "duplicate_track", "set_clip_loop", "set_track_arm",
    "set_send_level", "set_time_signature", "set_track_monitoring", "set_track_input_routing",
    "set_track_output_routing", "set_metronome", "set_clip_envelope", "clear_clip_envelope",
    "undo", "redo", "remove_notes", "quantize_clip",
    "duplicate_clip_loop", "duplicate_region", "set_device_enabled", "create_return_track",
    "delete_return_track", "stop_all_clips", "set_clip_gain", "set_clip_pitch",
    "set_clip_warping", "set_clip_warp_mode",
    "set_track_color", "set_clip_color", "set_scene_color",
    "create_locator", "rename_locator", "delete_locator", "jump_to_locator",
    "set_clip_groove", "set_groove_params", "add_warp_marker", "move_warp_marker",
    "remove_warp_marker", "capture_midi", "duplicate_scene", "move_device",
    "set_chain_mixer", "select_track", "select_scene", "select_clip", "focus_view",
    "fold_track", "transpose_clip_notes", "humanize_clip", "unarm_all", "set_track_height",
])

# Read-only commands; they run directly on the socket thread
READ_COMMANDS = frozenset([
    "get_session_info", "get_track_info", "get_track_routing",
    "get_device_parameters", "get_arrangement_info", "get_arrangement_clips",
    "get_full_arrangement", "get_clip_notes", "get_arrangement_clip_notes",
    "get_clip_envelope", "get_clip_info", "get_drum_pads",
    "get_browser_item", "get_browser_categories", "get_browser_items",
    "get_browser_tree", "get_browser_items_at_path",
    "get_locators", "get_groove_pool", "get_warp_markers", "get_rack_chains",
    "get_view_state",
])

def create_instance(c_instance):
    """Create and return the AbletonMCP script instance"""
    return AbletonMCP(c_instance)

class AbletonMCP(ControlSurface):
    """AbletonMCP Remote Script for Ableton Live"""
    
    def __init__(self, c_instance):
        """Initialize the control surface"""
        ControlSurface.__init__(self, c_instance)
        self.log_message("AbletonMCP Remote Script initializing...")
        
        # Socket server for communication
        self.server = None
        self.client_threads = []
        self.server_thread = None
        self.running = False
        
        # Cache the song reference for easier access
        self._song = self.song()

        # Event buffer fed by Live listeners (see get_events)
        self._events = []
        self._event_seq = 0
        self._event_cond = threading.Condition()
        self._song_listeners = []
        self._track_listeners = {}  # Live object pointer -> removers
        self._listened_song = None
        self._listened_song_ptr = None
        try:
            self._attach_listeners()
        except Exception as e:
            self.log_message("Attaching listeners failed: " + str(e))
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        self._detach_listeners()
        
        # Stop the server
        if self.server:
            try:
                self.server.close()
            except:
                pass
        
        # Wait for the server thread to exit
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(1.0)
            
        # Clean up any client threads
        for client_thread in self.client_threads[:]:
            if client_thread.is_alive():
                # We don't join them as they might be stuck
                self.log_message("Client thread still alive during disconnect")
        
        ControlSurface.disconnect(self)
        self.log_message("AbletonMCP disconnected")
    
    def start_server(self):
        """Start the socket server in a separate thread"""
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind((HOST, DEFAULT_PORT))
            self.server.listen(5)  # Allow up to 5 pending connections
            
            self.running = True
            self.server_thread = threading.Thread(target=self._server_thread)
            self.server_thread.daemon = True
            self.server_thread.start()
            
            self.log_message("Server started on port " + str(DEFAULT_PORT))
        except Exception as e:
            self.log_message("Error starting server: " + str(e))
            self.show_message("AbletonMCP: Error starting server - " + str(e))
    
    def _server_thread(self):
        """Server thread implementation - handles client connections"""
        try:
            self.log_message("Server thread started")
            # Set a timeout to allow regular checking of running flag
            self.server.settimeout(1.0)
            
            while self.running:
                try:
                    # Accept connections with timeout
                    client, address = self.server.accept()
                    self.log_message("Connection accepted from " + str(address))
                    self.show_message("AbletonMCP: Client connected")
                    
                    # Handle client in a separate thread
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client,)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                    # Keep track of client threads
                    self.client_threads.append(client_thread)
                    
                    # Clean up finished client threads
                    self.client_threads = [t for t in self.client_threads if t.is_alive()]
                    
                except socket.timeout:
                    # No connection yet, just continue
                    continue
                except Exception as e:
                    if self.running:  # Only log if still running
                        self.log_message("Server accept error: " + str(e))
                    time.sleep(0.5)
            
            self.log_message("Server thread stopped")
        except Exception as e:
            self.log_message("Server thread error: " + str(e))
    
    def _handle_client(self, client):
        """Handle communication with a connected client"""
        self.log_message("Client handler started")
        client.settimeout(None)  # No timeout for client socket
        buffer = ''  # Changed from b'' to '' for Python 2
        
        try:
            while self.running:
                try:
                    # Receive data
                    data = client.recv(8192)
                    
                    if not data:
                        # Client disconnected
                        self.log_message("Client disconnected")
                        break
                    
                    # Accumulate data in buffer with explicit encoding/decoding
                    try:
                        # Python 3: data is bytes, decode to string
                        buffer += data.decode('utf-8')
                    except AttributeError:
                        # Python 2: data is already string
                        buffer += data
                    
                    try:
                        # Try to parse command from buffer
                        command = json.loads(buffer)  # Removed decode('utf-8')
                        buffer = ''  # Clear buffer after successful parse
                        
                        self.log_message("Received command: " + str(command.get("type", "unknown")))
                        
                        # Process the command and get response
                        response = self._process_command(command)
                        
                        # Send the response with explicit encoding
                        try:
                            # Python 3: encode string to bytes
                            client.sendall(json.dumps(response).encode('utf-8'))
                        except AttributeError:
                            # Python 2: string is already bytes
                            client.sendall(json.dumps(response))
                    except ValueError:
                        # Incomplete data, wait for more
                        continue
                        
                except Exception as e:
                    self.log_message("Error handling client data: " + str(e))
                    self.log_message(traceback.format_exc())
                    
                    # Send error response if possible
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    try:
                        # Python 3: encode string to bytes
                        client.sendall(json.dumps(error_response).encode('utf-8'))
                    except AttributeError:
                        # Python 2: string is already bytes
                        client.sendall(json.dumps(error_response))
                    except:
                        # If we can't send the error, the connection is probably dead
                        break
                    
                    # For serious errors, break the loop
                    if not isinstance(e, ValueError):
                        break
        except Exception as e:
            self.log_message("Error in client handler: " + str(e))
        finally:
            try:
                client.close()
            except:
                pass
            self.log_message("Client handler stopped")
    
    def _process_command(self, command):
        """Process a command from the client and return a response"""
        # Refresh song reference — cached ref can become stale after doc swap
        self._song = self.song()
        command_type = command.get("type", "")
        params = command.get("params", {})
        
        # Initialize response
        response = {
            "status": "success",
            "result": {}
        }
        
        try:
            if command_type == "resample_master":
                # Runs on the socket thread: plays the arrangement in real time while recording
                response["result"] = self._resample_master(params.get("seconds"), params.get("name", "master rec"),
                                                           params.get("start_time", 0.0))
            elif command_type == "record_arrangement":
                # Runs on socket thread with schedule_message for main thread ops
                sections = params.get("sections", [])
                start_time = params.get("start_time", 0.0)
                response["result"] = self._record_arrangement(sections, start_time)
            elif command_type == "batch":
                response["result"] = self._batch(params.get("commands", []), params.get("stop_on_error", True))
            elif command_type == "search_browser":
                # Long walk of the browser: socket thread, not batchable (it would freeze Live's UI)
                response["result"] = self._search_browser(params.get("query", ""), params.get("category", "all"),
                                                          int(params.get("max_results", 30) or 30))
            elif command_type == "get_events":
                response["result"] = self._get_events(params.get("since", 0), params.get("timeout", 0.0),
                                                      params.get("limit", 500))
            elif command_type in MODIFYING_COMMANDS:
                # Live's object model isn't thread-safe: state changes run on the main thread
                response["result"] = self._on_main_thread(lambda: self._run_modifying(command_type, params))
            elif command_type in READ_COMMANDS:
                response["result"] = self._run_read(command_type, params)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response

    def _run_read(self, command_type, params):
        """Run one read-only command (safe on the socket thread or the main thread)."""
        if command_type == "get_session_info":
            return self._get_session_info()
        elif command_type == "get_track_info":
            track_index = params.get("track_index", 0)
            return self._get_track_info(track_index)
        elif command_type == "get_track_routing":
            track_index = params.get("track_index", 0)
            return self._get_track_routing(track_index)
        elif command_type == "get_device_parameters":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            return self._get_device_parameters(track_index, device_index)
        elif command_type == "get_arrangement_info":
            return self._get_arrangement_info()
        elif command_type == "get_arrangement_clips":
            track_index = params.get("track_index", 0)
            return self._get_arrangement_clips(track_index)
        elif command_type == "get_full_arrangement":
            return self._get_full_arrangement()
        elif command_type == "get_clip_notes":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            return self._get_clip_notes(track_index, clip_index)
        elif command_type == "get_arrangement_clip_notes":
            track_index = params.get("track_index", 0)
            arrangement_clip_index = params.get("arrangement_clip_index", 0)
            return self._get_arrangement_clip_notes(track_index, arrangement_clip_index)
        elif command_type == "get_clip_envelope":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            return self._get_clip_envelope(track_index, clip_index, device_index, parameter_index)
        elif command_type == "get_clip_info":
            return self._get_clip_info(params.get("track_index", 0), params.get("clip_index", 0),
                                       params.get("arrangement_clip_index"))
        elif command_type == "get_drum_pads":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            return self._get_drum_pads(track_index, device_index)
        elif command_type == "get_browser_item":
            uri = params.get("uri", None)
            path = params.get("path", None)
            return self._get_browser_item(uri, path)
        elif command_type == "get_browser_categories":
            category_type = params.get("category_type", "all")
            return self._get_browser_categories(category_type)
        elif command_type == "get_browser_items":
            path = params.get("path", "")
            item_type = params.get("item_type", "all")
            return self._get_browser_items(path, item_type)
        elif command_type == "get_browser_tree":
            category_type = params.get("category_type", "all")
            return self.get_browser_tree(category_type)
        elif command_type == "get_browser_items_at_path":
            path = params.get("path", "")
            return self.get_browser_items_at_path(path)
        elif command_type == "get_locators":
            return self._get_locators()
        elif command_type == "get_groove_pool":
            return self._get_groove_pool()
        elif command_type == "get_warp_markers":
            return self._get_warp_markers(params.get("track_index", 0), params.get("clip_index", 0),
                                          aci=params.get("arrangement_clip_index"))
        elif command_type == "get_rack_chains":
            return self._get_rack_chains(params.get("track_index", 0), params.get("device_index", 0))
        elif command_type == "get_view_state":
            return self._get_view_state()
        raise ValueError("Unknown command: " + command_type)

    def _run_modifying(self, command_type, params):
        """Run one state-modifying command. Call only on Live's main thread."""
        result = None
        if command_type == "create_midi_track":
            index = params.get("index", -1)
            result = self._create_midi_track(index)
        elif command_type == "set_track_name":
            track_index = params.get("track_index", 0)
            name = params.get("name", "")
            result = self._set_track_name(track_index, name)
        elif command_type == "set_track_monitoring":
            track_index = params.get("track_index", 0)
            state = params.get("state", 1)
            result = self._set_track_monitoring(track_index, state)
        elif command_type == "set_track_input_routing":
            track_index = params.get("track_index", 0)
            routing_type_name = params.get("routing_type_name", "")
            result = self._set_track_input_routing(track_index, routing_type_name, params.get("channel_name"))
        elif command_type == "set_track_output_routing":
            track_index = params.get("track_index", 0)
            routing_type_name = params.get("routing_type_name", "")
            result = self._set_track_output_routing(track_index, routing_type_name)
        elif command_type == "create_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            length = params.get("length", 4.0)
            result = self._create_clip(track_index, clip_index, length)
        elif command_type == "create_arrangement_audio_clip":
            track_index = params.get("track_index", 0)
            file_path = params.get("file_path", "")
            time = params.get("time", 0.0)
            length = params.get("length", None)
            start_offset = params.get("start_offset", None)
            result = self._create_arrangement_audio_clip(track_index, file_path, time, length, start_offset)
        elif command_type == "create_arrangement_audio_clips_batch":
            result = self._create_arrangement_audio_clips_batch(
                params.get("track_index", 0), params.get("file_path", ""), params.get("times", []),
                params.get("length", None), params.get("start_offset", None))
        elif command_type == "create_arrangement_midi_clip":
            track_index = params.get("track_index", 0)
            time = params.get("time", 0.0)
            length = params.get("length", 4.0)
            notes = params.get("notes", None)
            result = self._create_arrangement_midi_clip(track_index, time, length, notes)
        elif command_type == "delete_arrangement_clip":
            track_index = params.get("track_index", 0)
            arrangement_clip_index = params.get("arrangement_clip_index", 0)
            result = self._delete_arrangement_clip(track_index, arrangement_clip_index)
        elif command_type == "add_notes_to_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            notes = params.get("notes", [])
            result = self._add_notes_to_clip(track_index, clip_index, notes)
        elif command_type == "set_clip_name":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            name = params.get("name", "")
            result = self._set_clip_name(track_index, clip_index, name, aci=params.get("arrangement_clip_index"))
        elif command_type == "set_tempo":
            tempo = params.get("tempo", 120.0)
            result = self._set_tempo(tempo)
        elif command_type == "fire_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._fire_clip(track_index, clip_index)
        elif command_type == "stop_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._stop_clip(track_index, clip_index)
        elif command_type == "start_playback":
            result = self._start_playback()
        elif command_type == "stop_playback":
            result = self._stop_playback()
        elif command_type == "play_arrangement":
            time = params.get("time", None)
            result = self._play_arrangement(time)
        elif command_type == "load_instrument_or_effect":
            track_index = params.get("track_index", 0)
            uri = params.get("uri", "")
            clip_index = params.get("clip_index", None)
            result = self._load_browser_item(track_index, uri, clip_index=clip_index)
        elif command_type == "load_browser_item":
            track_index = params.get("track_index", 0)
            item_uri = params.get("item_uri", "")
            clip_index = params.get("clip_index", None)
            result = self._load_browser_item(track_index, item_uri, clip_index=clip_index)
        elif command_type == "set_device_parameter":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_index = params.get("parameter_index", 0)
            value = params.get("value", 0.0)
            result = self._set_device_parameter(track_index, device_index, parameter_index, value)
        elif command_type == "batch_set_device_parameters":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            parameter_indices = params.get("parameter_indices", [])
            values = params.get("values", [])
            result = self._batch_set_device_parameters(track_index, device_index, parameter_indices, values)
        elif command_type == "set_track_volume":
            track_index = params.get("track_index", 0)
            volume = params.get("volume", 0.85)
            result = self._set_track_volume(track_index, volume)
        elif command_type == "set_track_panning":
            track_index = params.get("track_index", 0)
            panning = params.get("panning", 0.0)
            result = self._set_track_panning(track_index, panning)
        elif command_type == "fire_scene":
            scene_index = params.get("scene_index", 0)
            result = self._fire_scene(scene_index)
        elif command_type == "set_song_time":
            time = params.get("time", 0.0)
            result = self._set_song_time(time)
        elif command_type == "set_record_mode":
            on = params.get("on", False)
            result = self._set_record_mode(on)
        elif command_type == "set_arrangement_overdub":
            on = params.get("on", False)
            result = self._set_arrangement_overdub(on)
        elif command_type == "set_back_to_arranger":
            result = self._set_back_to_arranger(params.get("value", False))
        elif command_type == "set_arrangement_loop":
            on = params.get("on", True)
            start = params.get("start", 0.0)
            length = params.get("length", 16.0)
            result = self._set_arrangement_loop(on, start, length)
        elif command_type == "set_track_mute":
            track_index = params.get("track_index", 0)
            mute = params.get("mute", False)
            result = self._set_track_mute(track_index, mute)
        elif command_type == "set_track_solo":
            track_index = params.get("track_index", 0)
            solo = params.get("solo", False)
            result = self._set_track_solo(track_index, solo)
        elif command_type == "delete_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            result = self._delete_clip(track_index, clip_index)
        elif command_type == "duplicate_clip":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            target_index = params.get("target_index", -1)
            result = self._duplicate_clip(track_index, clip_index, target_index)
        elif command_type == "create_scene":
            index = params.get("index", -1)
            result = self._create_scene(index)
        elif command_type == "delete_scene":
            scene_index = params.get("scene_index", 0)
            result = self._delete_scene(scene_index)
        elif command_type == "set_scene_name":
            scene_index = params.get("scene_index", 0)
            name = params.get("name", "")
            result = self._set_scene_name(scene_index, name)
        elif command_type == "create_audio_track":
            index = params.get("index", -1)
            result = self._create_audio_track(index)
        elif command_type == "delete_track":
            track_index = params.get("track_index", 0)
            result = self._delete_track(track_index)
        elif command_type == "delete_device":
            track_index = params.get("track_index", 0)
            device_index = params.get("device_index", 0)
            result = self._delete_device(track_index, device_index)
        elif command_type == "duplicate_track":
            track_index = params.get("track_index", 0)
            result = self._duplicate_track(track_index)
        elif command_type == "set_clip_loop":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            loop_start = params.get("loop_start", None)
            loop_end = params.get("loop_end", None)
            looping = params.get("looping", None)
            result = self._set_clip_loop(track_index, clip_index, loop_start, loop_end, looping)
        elif command_type == "set_track_arm":
            track_index = params.get("track_index", 0)
            arm = params.get("arm", False)
            result = self._set_track_arm(track_index, arm)
        elif command_type == "set_send_level":
            track_index = params.get("track_index", 0)
            send_index = params.get("send_index", 0)
            value = params.get("value", 0.0)
            result = self._set_send_level(track_index, send_index, value)
        elif command_type == "set_time_signature":
            numerator = params.get("numerator", 4)
            denominator = params.get("denominator", 4)
            result = self._set_time_signature(numerator, denominator)
        elif command_type == "set_metronome":
            on = params.get("on", False)
            result = self._set_metronome(on)
        elif command_type == "set_clip_envelope":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            parameter_index = params.get("parameter_index", 0)
            device_index = params.get("device_index", 0)
            points = params.get("points", [])
            result = self._set_clip_envelope(track_index, clip_index, device_index, parameter_index, points)
        elif command_type == "clear_clip_envelope":
            track_index = params.get("track_index", 0)
            clip_index = params.get("clip_index", 0)
            parameter_index = params.get("parameter_index", 0)
            device_index = params.get("device_index", 0)
            result = self._clear_clip_envelope(track_index, clip_index, device_index, parameter_index)
        elif command_type == "undo":
            result = self._undo()
        elif command_type == "redo":
            result = self._redo()
        elif command_type == "remove_notes":
            result = self._remove_notes(params.get("track_index", 0), params.get("clip_index", 0),
                                        params.get("from_pitch", 0), params.get("pitch_span", 128),
                                        params.get("from_time", 0.0), params.get("time_span", -1.0), aci=params.get("arrangement_clip_index"))
        elif command_type == "quantize_clip":
            result = self._quantize_clip(params.get("track_index", 0), params.get("clip_index", 0),
                                         params.get("grid", 5), params.get("strength", 1.0), aci=params.get("arrangement_clip_index"))
        elif command_type == "duplicate_clip_loop":
            result = self._duplicate_clip_loop(params.get("track_index", 0), params.get("clip_index", 0), aci=params.get("arrangement_clip_index"))
        elif command_type == "duplicate_region":
            result = self._duplicate_region(params.get("track_index", 0), params.get("clip_index", 0),
                                            params.get("region_start", 0.0), params.get("region_length", 4.0),
                                            params.get("destination_time", 4.0), params.get("pitch", -1),
                                            params.get("transposition_amount", 0), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_device_enabled":
            result = self._set_device_enabled(params.get("track_index", 0), params.get("device_index", 0),
                                              params.get("enabled", True))
        elif command_type == "create_return_track":
            result = self._create_return_track()
        elif command_type == "delete_return_track":
            result = self._delete_return_track(params.get("index", 0))
        elif command_type == "stop_all_clips":
            result = self._stop_all_clips(params.get("quantized", True))
        elif command_type == "set_clip_gain":
            result = self._set_clip_gain(params.get("track_index", 0), params.get("clip_index", 0), params.get("gain", 0.0), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_clip_pitch":
            result = self._set_clip_pitch(params.get("track_index", 0), params.get("clip_index", 0),
                                          params.get("coarse", None), params.get("fine", None), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_clip_warping":
            result = self._set_clip_warping(params.get("track_index", 0), params.get("clip_index", 0), params.get("warping", True), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_clip_warp_mode":
            result = self._set_clip_warp_mode(params.get("track_index", 0), params.get("clip_index", 0), params.get("warp_mode", 0), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_track_color":
            result = self._set_track_color(params.get("track_index", 0), params.get("color"), params.get("color_index"))
        elif command_type == "set_clip_color":
            result = self._set_clip_color(params.get("track_index", 0), params.get("clip_index", 0),
                                          params.get("color"), params.get("color_index"), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_scene_color":
            result = self._set_scene_color(params.get("scene_index", 0), params.get("color"), params.get("color_index"))
        elif command_type == "create_locator":
            result = self._create_locator(params.get("time", 0.0), params.get("name"))
        elif command_type == "rename_locator":
            result = self._rename_locator(params.get("locator_index", 0), params.get("name", ""))
        elif command_type == "delete_locator":
            result = self._delete_locator(params.get("locator_index", 0))
        elif command_type == "jump_to_locator":
            result = self._jump_to_locator(params.get("locator_index", 0))
        elif command_type == "set_clip_groove":
            result = self._set_clip_groove(params.get("track_index", 0), params.get("clip_index", 0),
                                           params.get("groove_index", -1), aci=params.get("arrangement_clip_index"))
        elif command_type == "set_groove_params":
            result = self._set_groove_params(params.get("groove_index"), params.get("timing_amount"),
                                             params.get("random_amount"), params.get("velocity_amount"),
                                             params.get("quantization_amount"), params.get("base"),
                                             params.get("global_amount"))
        elif command_type == "add_warp_marker":
            result = self._add_warp_marker(params.get("track_index", 0), params.get("clip_index", 0),
                                           params.get("beat_time", 0.0), params.get("sample_time"),
                                           aci=params.get("arrangement_clip_index"))
        elif command_type == "move_warp_marker":
            result = self._move_warp_marker(params.get("track_index", 0), params.get("clip_index", 0),
                                            params.get("beat_time", 0.0), params.get("beat_time_distance", 0.0),
                                            aci=params.get("arrangement_clip_index"))
        elif command_type == "remove_warp_marker":
            result = self._remove_warp_marker(params.get("track_index", 0), params.get("clip_index", 0),
                                              params.get("beat_time", 0.0), aci=params.get("arrangement_clip_index"))
        elif command_type == "capture_midi":
            result = self._capture_midi(params.get("destination", 0))
        elif command_type == "duplicate_scene":
            result = self._duplicate_scene(params.get("scene_index", 0))
        elif command_type == "move_device":
            result = self._move_device(params.get("track_index", 0), params.get("device_index", 0),
                                       params.get("new_index", 0), params.get("target_track_index"))
        elif command_type == "set_chain_mixer":
            result = self._set_chain_mixer(params.get("track_index", 0), params.get("device_index", 0),
                                           params.get("chain_index", 0), params.get("mute"), params.get("solo"),
                                           params.get("volume"), params.get("panning"))
        elif command_type == "select_track":
            result = self._select_track(params.get("track_index", 0))
        elif command_type == "select_scene":
            result = self._select_scene(params.get("scene_index", 0))
        elif command_type == "select_clip":
            result = self._select_clip(params.get("track_index", 0), params.get("clip_index", 0),
                                       aci=params.get("arrangement_clip_index"))
        elif command_type == "focus_view":
            result = self._focus_view(params.get("view", "Arranger"))
        elif command_type == "fold_track":
            result = self._fold_track(params.get("track_index", 0), params.get("fold", True))
        elif command_type == "transpose_clip_notes":
            result = self._transpose_clip_notes(params.get("track_index", 0), params.get("clip_index", 0),
                                                params.get("semitones", 0), params.get("from_pitch", 0),
                                                params.get("pitch_span", 128), params.get("from_time", 0.0),
                                                params.get("time_span", -1.0), aci=params.get("arrangement_clip_index"))
        elif command_type == "humanize_clip":
            result = self._humanize_clip(params.get("track_index", 0), params.get("clip_index", 0),
                                         params.get("timing", 0.0), params.get("velocity", 0), params.get("seed"),
                                         params.get("from_time", 0.0), params.get("time_span", -1.0),
                                         aci=params.get("arrangement_clip_index"))
        elif command_type == "unarm_all":
            result = self._unarm_all()
        elif command_type == "set_track_height":
            result = self._set_track_height(params.get("track_index", 0), params.get("steps", 0),
                                            params.get("collapsed"), params.get("all_tracks", False))
        else:
            raise ValueError("Unknown command: " + command_type)
        return result

    def _on_main_thread(self, fn, timeout=10.0):
        """Run fn on Live's main thread and return its result (raises its exception)."""
        response_queue = queue.Queue()

        def task():
            try:
                result = fn()
                # Tracks the command added are watched before the caller hears back
                self._sync_listeners()
                response_queue.put(("ok", result))
            except Exception as e:
                self.log_message("Error in main thread task: " + str(e))
                self.log_message(traceback.format_exc())
                response_queue.put(("error", e))

        try:
            self.schedule_message(0, task)
        except AssertionError:
            # Already on the main thread
            task()
        try:
            status, value = response_queue.get(timeout=timeout)
        except queue.Empty:
            raise RuntimeError("Timeout waiting for operation to complete")
        if status == "error":
            raise value
        return value

    # ---- batch ----

    def _resolve_refs(self, value, results):
        """Replace {"$ref": [i, "key", ...]} with results[i]["result"]["key"]... (earlier batch results)."""
        if isinstance(value, dict):
            if list(value.keys()) == ["$ref"]:
                path = value["$ref"]
                if not isinstance(path, list) or not path:
                    raise ValueError("$ref must be a list like [0, \"index\"]")
                i = path[0]
                if not isinstance(i, int) or not 0 <= i < len(results):
                    raise ValueError("$ref points at command %r, which hasn't run" % (i,))
                if results[i].get("status") != "success":
                    raise ValueError("$ref points at command %d, which failed" % i)
                v = results[i]["result"]
                for key in path[1:]:
                    v = v[key]
                return v
            return dict((k, self._resolve_refs(v, results)) for k, v in value.items())
        if isinstance(value, list):
            return [self._resolve_refs(v, results) for v in value]
        return value

    def _batch(self, commands, stop_on_error=True):
        """Run many commands in one main-thread task (one Live tick instead of one per command).

        commands: [{"type": ..., "params": {...}}, ...]. Params may reference earlier results with
        {"$ref": [i, "key", ...]}, e.g. the index of a track created by command 0.
        Returns {"results": [{"status", "result"|"message"}, ...], "completed": n}.
        """
        if not isinstance(commands, list) or not commands:
            raise ValueError("batch needs a non-empty 'commands' list")
        for i, c in enumerate(commands):
            t = c.get("type") if isinstance(c, dict) else None
            if t not in MODIFYING_COMMANDS and t not in READ_COMMANDS:
                raise ValueError("batch command %d: %r can't be batched (unknown, or a long-running/"
                                 "streaming command like record_arrangement or get_events)" % (i, t))

        def run_all():
            results = []
            for c in commands:
                t = c["type"]
                try:
                    p = self._resolve_refs(c.get("params", {}) or {}, results)
                    r = self._run_modifying(t, p) if t in MODIFYING_COMMANDS else self._run_read(t, p)
                    results.append({"status": "success", "result": r})
                except Exception as e:
                    results.append({"status": "error", "type": t, "message": str(e)})
                    if stop_on_error:
                        break
            return results

        results = self._on_main_thread(run_all, timeout=max(10.0, 0.5 * len(commands)))
        return {"results": results, "completed": len(results), "total": len(commands),
                "ok": all(r["status"] == "success" for r in results) and len(results) == len(commands)}

    # ---- events: Live listeners pushed into a buffer that clients poll or long-poll ----

    def _emit(self, event_type, **data):
        """Record an event (called from listener callbacks on the main thread)."""
        with self._event_cond:
            self._event_seq += 1
            data["seq"] = self._event_seq
            data["type"] = event_type
            data["time"] = time.time()
            try:
                data["beat"] = round(self._listened_song.current_song_time, 3)
            except Exception:
                pass
            self._events.append(data)
            if len(self._events) > EVENT_BUFFER_SIZE:
                del self._events[:len(self._events) - EVENT_BUFFER_SIZE]
            self._event_cond.notify_all()

    def _listen(self, subject, prop, callback, into):
        """Add a Live listener and append its remover to the list `into`."""
        add = getattr(subject, "add_%s_listener" % prop, None)
        if add is None:
            return
        try:
            add(callback)
        except Exception as e:
            self.log_message("Can't listen to %s: %s" % (prop, e))
            return
        remove = getattr(subject, "remove_%s_listener" % prop)
        into.append(lambda: remove(callback))

    @staticmethod
    def _ptr(obj):
        # Every access to a Live object returns a new Python wrapper; _live_ptr identifies the object
        return getattr(obj, "_live_ptr", id(obj))

    def _detach_listeners(self):
        removers = self._song_listeners + [r for rs in self._track_listeners.values() for r in rs]
        for remove in removers:
            try:
                remove()
            except Exception:
                pass
        self._song_listeners = []
        self._track_listeners = {}

    def _attach_listeners(self):
        """Attach every listener to the current song from scratch. Main thread only."""
        self._detach_listeners()
        song = self.song()
        self._listened_song = song
        self._listened_song_ptr = self._ptr(song)
        into = self._song_listeners

        def song_prop(prop):
            self._listen(song, prop, lambda: self._emit(prop, value=getattr(song, prop)), into)

        for prop in ("is_playing", "tempo", "record_mode", "signature_numerator",
                     "signature_denominator", "loop", "metronome", "arrangement_overdub"):
            song_prop(prop)
        # Track or scene lists changed: watch the new tracks too
        for prop in ("tracks", "scenes", "return_tracks"):
            self._listen(song, prop, lambda p=prop: self._on_structure_changed(p), into)
        view = song.view
        self._listen(view, "selected_track",
                     lambda: self._emit("selected_track", name=view.selected_track.name,
                                        index=self._track_index(view.selected_track)), into)
        self._listen(view, "selected_scene",
                     lambda: self._emit("selected_scene", name=view.selected_scene.name,
                                        index=self._scene_index(view.selected_scene)), into)
        self._sync_track_listeners()

    def _sync_listeners(self):
        """Follow a new set or added/removed tracks, leaving existing listeners alone. Main thread only.

        Removing and re-adding a listener drops notifications Live has queued for it, so this only
        touches what changed."""
        try:
            if self._ptr(self.song()) != self._listened_song_ptr:
                self._attach_listeners()
            else:
                self._sync_track_listeners()
        except Exception as e:
            self.log_message("Syncing listeners failed: " + str(e))

    def _sync_track_listeners(self):
        song = self._listened_song
        current = dict((self._ptr(t), t) for t in
                       list(song.tracks) + list(song.return_tracks) + [song.master_track])
        for ptr in list(self._track_listeners):
            if ptr not in current:
                for remove in self._track_listeners.pop(ptr):
                    try:
                        remove()
                    except Exception:
                        pass
        for ptr, track in current.items():
            if ptr not in self._track_listeners:
                self._track_listeners[ptr] = []
                self._attach_track_listeners(track, self._track_listeners[ptr])

    def _attach_track_listeners(self, track, into):
        is_master = self._ptr(track) == self._ptr(self._listened_song.master_track)
        is_return = any(self._ptr(track) == self._ptr(t) for t in self._listened_song.return_tracks)

        def slot_event(kind, attr):
            def cb():
                slot = getattr(track, attr)
                if kind == "clip_fired" and slot == -1:
                    return  # the fired clip started (or was cancelled): clip_playing tells which
                data = {"track_index": self._track_index(track), "track": track.name, "clip_index": slot}
                if slot >= 0:
                    try:
                        data["clip"] = track.clip_slots[slot].clip.name
                    except Exception:
                        pass
                self._emit(kind, **data)
            return cb

        if not is_master and not is_return:
            # >= 0: session clip slot; -1: stopped; -2: playing the arrangement
            self._listen(track, "playing_slot_index", slot_event("clip_playing", "playing_slot_index"), into)
            self._listen(track, "fired_slot_index", slot_event("clip_fired", "fired_slot_index"), into)
        if not is_master:
            for prop in ("mute", "solo", "name"):
                self._listen(track, prop, lambda p=prop: self._emit(
                    "track_" + p, track_index=self._track_index(track), track=track.name,
                    value=getattr(track, p)), into)
            if not is_return and getattr(track, "can_be_armed", False):
                self._listen(track, "arm", lambda: self._emit(
                    "track_arm", track_index=self._track_index(track), track=track.name,
                    value=track.arm), into)

    def _track_index(self, track):
        """Current index (tracks 0+, master -1, returns -2, -3...), looked up when the event fires."""
        song = self._listened_song
        ptr = self._ptr(track)
        if ptr == self._ptr(song.master_track):
            return -1
        for i, t in enumerate(song.tracks):
            if self._ptr(t) == ptr:
                return i
        for i, t in enumerate(song.return_tracks):
            if self._ptr(t) == ptr:
                return -2 - i
        return None

    def _scene_index(self, scene):
        ptr = self._ptr(scene)
        for i, s in enumerate(self._listened_song.scenes):
            if self._ptr(s) == ptr:
                return i
        return None

    def _on_structure_changed(self, prop):
        self._emit(prop + "_changed", count=len(getattr(self._listened_song, prop)))
        # Can't add listeners from inside a notification; do it on the next tick (commands sent
        # through this script sync before they return, see _on_main_thread)
        self.schedule_message(1, self._sync_listeners)

    def _get_events(self, since=0, timeout=0.0, limit=500):
        """Events with seq > since. With timeout > 0, wait up to that long (max 30 s) for one."""
        if self._ptr(self.song()) != self._listened_song_ptr:
            # A different set was loaded; point the listeners at it
            try:
                self._on_main_thread(self._sync_listeners)
            except Exception as e:
                self.log_message("Re-attaching listeners failed: " + str(e))
        timeout = min(max(float(timeout or 0), 0.0), 30.0)
        deadline = time.time() + timeout
        with self._event_cond:
            while self._event_seq <= since and time.time() < deadline:
                self._event_cond.wait(deadline - time.time())
            events = [e for e in self._events if e["seq"] > since]
            oldest = self._events[0]["seq"] if self._events else self._event_seq + 1
            return {"events": events[:limit], "latest": self._event_seq,
                    "truncated": len(events) > limit,
                    # Events after `since` were dropped from the buffer before being read
                    "missed": since < oldest - 1 and since < self._event_seq}

    
    # Command implementations
    
    def _get_session_info(self):
        """Get information about the current session"""
        try:
            result = {
                "tempo": self._song.tempo,
                "signature_numerator": self._song.signature_numerator,
                "signature_denominator": self._song.signature_denominator,
                "track_count": len(self._song.tracks),
                "return_track_count": len(self._song.return_tracks),
                "scene_count": len(self._song.scenes),
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            # One call gives Claude the whole layout instead of one get_track_info per track
            tracks = []
            for i, track in enumerate(self._song.tracks):
                entry = {"index": i, "name": track.name, "color_index": getattr(track, "color_index", None),
                         "is_midi_track": track.has_midi_input, "mute": track.mute}
                if getattr(track, "is_foldable", False):
                    entry["is_group"] = True
                if getattr(track, "is_grouped", False) and getattr(track, "group_track", None) is not None:
                    entry["group"] = track.group_track.name
                tracks.append(entry)
            result["tracks"] = tracks
            result["return_tracks"] = [{"index": -2 - i, "name": t.name}
                                       for i, t in enumerate(self._song.return_tracks)]
            try:
                result["locator_count"] = len(self._song.cue_points)
                result["groove_count"] = len(self._song.groove_pool.grooves)
            except Exception:
                pass
            try:
                app = self.application()
                result["cpu_average"] = getattr(app, "average_process_usage", None)
                result["cpu_peak"] = getattr(app, "peak_process_usage", None)
            except Exception:
                pass
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            track = self._get_track(track_index)

            # Get clip slots (master and return tracks have none)
            clip_slots = []
            for slot_index, slot in enumerate(getattr(track, "clip_slots", []) or []):
                clip_info = None
                if slot.has_clip:
                    clip = slot.clip
                    clip_info = {
                        "name": clip.name,
                        "length": clip.length,
                        "is_playing": clip.is_playing,
                        "is_recording": clip.is_recording
                    }
                
                clip_slots.append({
                    "index": slot_index,
                    "has_clip": slot.has_clip,
                    "clip": clip_info
                })
            
            # Get devices
            devices = []
            for device_index, device in enumerate(track.devices):
                devices.append({
                    "index": device_index,
                    "name": device.name,
                    "class_name": device.class_name,
                    "type": self._get_device_type(device)
                })
            
            can_arm = getattr(track, "can_be_armed", False)
            volume = track.mixer_device.volume
            result = {
                "index": track_index,
                "name": track.name,
                "color_index": getattr(track, "color_index", None),
                "is_audio_track": getattr(track, "has_audio_input", False),
                "is_midi_track": getattr(track, "has_midi_input", False),
                "mute": getattr(track, "mute", None) if track_index != -1 else None,
                "solo": getattr(track, "solo", None) if track_index != -1 else None,
                "arm": track.arm if can_arm else False,
                "volume": volume.value,
                "volume_display": volume.str_for_value(volume.value),
                "panning": track.mixer_device.panning.value,
                "sends": [{"index": i, "value": s.value, "display": s.str_for_value(s.value)}
                          for i, s in enumerate(track.mixer_device.sends)],
                "output_meter_level": getattr(track, "output_meter_level", None),   # 0-1, live signal at the track output
                "clip_slots": clip_slots,
                "devices": devices
            }
            try:
                result["collapsed"] = bool(track.view.is_collapsed)
            except Exception:
                pass
            if getattr(track, "is_foldable", False):
                result["is_group"] = True
                result["folded"] = bool(track.fold_state)
            if getattr(track, "is_grouped", False) and getattr(track, "group_track", None) is not None:
                result["group"] = track.group_track.name
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
            raise
    
    def _set_track_monitoring(self, track_index, state):
        """Set track monitoring state (0=In, 1=Auto, 2=Off)"""
        try:
            track = self._get_track(track_index)
            track.current_monitoring_state = state
            return {"monitoring_state": track.current_monitoring_state}
        except Exception as e:
            self.log_message("Error setting track monitoring: " + str(e))
            raise

    def _get_track_routing(self, track_index):
        """Get input/output routing info for a track"""
        try:
            track = self._get_track(track_index)
            result = {
                "input_routing_type": str(track.input_routing_type.display_name) if hasattr(track.input_routing_type, 'display_name') else str(track.input_routing_type),
                "output_routing_type": str(track.output_routing_type.display_name) if hasattr(track.output_routing_type, 'display_name') else str(track.output_routing_type),
            }
            try:
                ch = getattr(track, "input_routing_channel", None)
                result["input_routing_channel"] = str(ch.display_name) if ch is not None else None
                result["available_input_routing_channels"] = [str(c.display_name) for c in track.available_input_routing_channels]
            except Exception:
                pass
            if hasattr(track, 'available_input_routing_types'):
                result["available_input_routing_types"] = [
                    {"display_name": str(r.display_name) if hasattr(r, 'display_name') else str(r)}
                    for r in track.available_input_routing_types
                ]
            if hasattr(track, 'available_output_routing_types'):
                result["available_output_routing_types"] = [
                    {"display_name": str(r.display_name) if hasattr(r, 'display_name') else str(r)}
                    for r in track.available_output_routing_types
                ]
            return result
        except Exception as e:
            self.log_message("Error getting track routing: " + str(e))
            raise

    def _set_track_input_routing(self, track_index, routing_type_name, channel_name=None):
        """Set track input routing by name; `channel_name` picks the channel ("Ch. 5", "1/2",
        "Post FX"), otherwise the type's first channel."""
        try:
            track = self._get_track(track_index)
            for routing_type in track.available_input_routing_types:
                name = str(routing_type.display_name) if hasattr(routing_type, 'display_name') else str(routing_type)
                if name == routing_type_name:
                    track.input_routing_type = routing_type
                    # the channel is a separate property and can stay pointed at the previous
                    # type's channel (recording then captures silence); pick the new type's first
                    chosen = None
                    try:
                        channels = list(track.available_input_routing_channels)
                        pick = channels[0] if channels else None
                        if channel_name:
                            want = str(channel_name).lower()
                            for c in channels:
                                if str(c.display_name).lower() == want:
                                    pick = c
                                    break
                            else:
                                raise Exception("no input channel %r; available: %s" % (
                                    channel_name, ", ".join(str(c.display_name) for c in channels)))
                        if pick is not None:
                            track.input_routing_channel = pick
                            chosen = str(pick.display_name)
                    except Exception as ce:
                        if channel_name:
                            raise
                        self.log_message("input channel not set: " + str(ce))
                    return {"input_routing_type": routing_type_name, "input_routing_channel": chosen}
            raise Exception("Routing type not found: " + routing_type_name)
        except Exception as e:
            self.log_message("Error setting track input routing: " + str(e))
            raise

    def _set_track_output_routing(self, track_index, routing_type_name):
        """Set track output routing by name"""
        try:
            track = self._get_track(track_index)
            available = []
            for routing_type in track.available_output_routing_types:
                name = str(routing_type.display_name) if hasattr(routing_type, 'display_name') else str(routing_type)
                available.append(name)
                if name.lower() == routing_type_name.lower():
                    track.output_routing_type = routing_type
                    return {"output_routing_type": name}
            raise Exception("Routing type not found: " + routing_type_name + ". Available: " + ", ".join(available))
        except Exception as e:
            self.log_message("Error setting track output routing: " + str(e))
            raise

    def _get_track(self, track_index):
        """Get a track by index. Use -1 for master track, -2/-3/etc for return tracks."""
        if track_index == -1:
            return self._song.master_track
        elif track_index < -1:
            return_index = -(track_index + 2)  # -2 -> 0, -3 -> 1
            if return_index < 0 or return_index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            return self._song.return_tracks[return_index]
        else:
            if track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            return self._song.tracks[track_index]

    def _set_track_volume(self, track_index, volume):
        """Set a track's volume using a normalized value (0.0 to 1.0)"""
        try:
            track = self._get_track(track_index)
            if volume < 0.0 or volume > 1.0:
                raise ValueError("Volume must be between 0.0 and 1.0")
            vol_param = track.mixer_device.volume
            actual_value = vol_param.min + volume * (vol_param.max - vol_param.min)
            vol_param.value = actual_value
            return {
                "track_name": track.name,
                "volume": vol_param.value,
                "normalized_volume": volume
            }
        except Exception as e:
            self.log_message("Error setting track volume: " + str(e))
            raise

    def _set_track_panning(self, track_index, panning):
        """Set a track's panning using a normalized value (0.0 to 1.0, 0.5 = center)"""
        try:
            track = self._get_track(track_index)
            if panning < 0.0 or panning > 1.0:
                raise ValueError("Panning must be between 0.0 and 1.0")
            pan_param = track.mixer_device.panning
            actual_value = pan_param.min + panning * (pan_param.max - pan_param.min)
            pan_param.value = actual_value
            return {
                "track_name": track.name,
                "panning": pan_param.value,
                "normalized_panning": panning
            }
        except Exception as e:
            self.log_message("Error setting track panning: " + str(e))
            raise

    def _get_arrangement_info(self):
        """Get current arrangement state"""
        try:
            return {
                "current_song_time": self._song.current_song_time,
                "is_playing": self._song.is_playing,
                "record_mode": self._song.record_mode,
                "arrangement_overdub": self._song.arrangement_overdub,
                "back_to_arranger": self._song.back_to_arranger,
                "loop": self._song.loop,
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length,
                "tempo": self._song.tempo,
                "scene_count": len(self._song.scenes),
                "song_length": self._song.song_length
            }
        except Exception as e:
            self.log_message("Error getting arrangement info: " + str(e))
            raise

    def _fire_scene(self, scene_index):
        """Fire all clips in a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range (0-{0})".format(len(self._song.scenes) - 1))
            scene = self._song.scenes[scene_index]
            scene.fire()
            return {
                "scene_index": scene_index,
                "scene_name": scene.name,
                "fired": True
            }
        except Exception as e:
            self.log_message("Error firing scene: " + str(e))
            raise

    def _set_song_time(self, time):
        """Set the current song time (arrangement position) in beats.
        Retries up to 5 times if the position doesn't land correctly."""
        try:
            target = max(0.0, time)
            for attempt in range(5):
                self._song.current_song_time = target
                actual = self._song.current_song_time
                if abs(actual - target) < 0.5:
                    break
                self.log_message("set_song_time attempt {0}: wanted {1}, got {2}".format(
                    attempt + 1, target, actual))
            return {
                "current_song_time": self._song.current_song_time
            }
        except Exception as e:
            self.log_message("Error setting song time: " + str(e))
            raise

    def _set_record_mode(self, on):
        """Enable or disable arrangement recording"""
        try:
            self._song.record_mode = 1 if on else 0
            return {
                "record_mode": self._song.record_mode
            }
        except Exception as e:
            self.log_message("Error setting record mode: " + str(e))
            raise

    def _set_arrangement_overdub(self, on):
        """Enable or disable arrangement overdub"""
        try:
            self._song.arrangement_overdub = 1 if on else 0
            return {
                "arrangement_overdub": self._song.arrangement_overdub
            }
        except Exception as e:
            self.log_message("Error setting arrangement overdub: " + str(e))
            raise

    def _set_back_to_arranger(self, value=False):
        """Song.back_to_arranger is True while session clips override the arrangement (the
        'Back to Arrangement' button is lit). Setting it False is what clicking that button
        does: the arrangement plays again. Default False; pass True to hand control to session."""
        try:
            self._song.back_to_arranger = bool(value)
            return {
                "back_to_arranger": self._song.back_to_arranger
            }
        except Exception as e:
            self.log_message("Error setting back to arranger: " + str(e))
            raise

    def _set_arrangement_loop(self, on, start, length):
        """Set arrangement loop on/off, start position and length in beats"""
        try:
            self._song.loop = on
            if start is not None:
                self._song.loop_start = max(0.0, start)
            if length is not None:
                self._song.loop_length = max(0.0, length)
            return {
                "loop": self._song.loop,
                "loop_start": self._song.loop_start,
                "loop_length": self._song.loop_length
            }
        except Exception as e:
            self.log_message("Error setting arrangement loop: " + str(e))
            raise

    def _set_track_mute(self, track_index, mute):
        """Mute or unmute a track"""
        try:
            track = self._get_track(track_index)
            track.mute = mute
            return {
                "track_name": track.name,
                "mute": track.mute
            }
        except Exception as e:
            self.log_message("Error setting track mute: " + str(e))
            raise

    def _set_track_solo(self, track_index, solo):
        """Solo or unsolo a track"""
        try:
            track = self._get_track(track_index)
            track.solo = solo
            return {
                "track_name": track.name,
                "solo": track.solo
            }
        except Exception as e:
            self.log_message("Error setting track solo: " + str(e))
            raise

    def _delete_clip(self, track_index, clip_index):
        """Delete a clip from a clip slot"""
        try:
            track = self._get_track(track_index)
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise ValueError("No clip in slot {0}".format(clip_index))
            clip_slot.delete_clip()
            return {
                "track_name": track.name,
                "clip_index": clip_index,
                "deleted": True
            }
        except Exception as e:
            self.log_message("Error deleting clip: " + str(e))
            raise

    def _duplicate_clip(self, track_index, clip_index, target_index):
        """Duplicate a clip to another slot"""
        try:
            track = self._get_track(track_index)
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Source clip index out of range")
            if not track.clip_slots[clip_index].has_clip:
                raise ValueError("No clip in source slot {0}".format(clip_index))
            if target_index < 0:
                # Find next empty slot
                target_index = -1
                for i in range(len(track.clip_slots)):
                    if not track.clip_slots[i].has_clip:
                        target_index = i
                        break
                if target_index < 0:
                    raise ValueError("No empty clip slots available")
            if target_index >= len(track.clip_slots):
                raise IndexError("Target clip index out of range")
            if track.clip_slots[target_index].has_clip:
                raise ValueError("Target slot {0} already has a clip".format(target_index))
            track.clip_slots[clip_index].duplicate_clip_to(track.clip_slots[target_index])
            return {
                "track_name": track.name,
                "source_index": clip_index,
                "target_index": target_index,
                "duplicated": True
            }
        except Exception as e:
            self.log_message("Error duplicating clip: " + str(e))
            raise

    def _create_scene(self, index):
        """Create a new scene at the specified index"""
        try:
            if index < 0:
                index = len(self._song.scenes)
            scene = self._song.create_scene(index)
            return {
                "scene_index": index,
                "scene_count": len(self._song.scenes)
            }
        except Exception as e:
            self.log_message("Error creating scene: " + str(e))
            raise

    def _set_scene_name(self, scene_index, name):
        """Set a scene's name"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            self._song.scenes[scene_index].name = name
            return {
                "scene_index": scene_index,
                "name": self._song.scenes[scene_index].name
            }
        except Exception as e:
            self.log_message("Error setting scene name: " + str(e))
            raise

    def _create_audio_track(self, index):
        """Create a new audio track at the specified index"""
        try:
            if index < 0:
                index = len(self._song.tracks)
            self._song.create_audio_track(index)
            track = self._song.tracks[index]
            return {
                "index": index,
                "name": track.name,
                "track_count": len(self._song.tracks)
            }
        except Exception as e:
            self.log_message("Error creating audio track: " + str(e))
            raise

    def _delete_track(self, track_index):
        """Delete a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track_name = self._song.tracks[track_index].name
            self._song.delete_track(track_index)
            return {
                "deleted_track": track_name,
                "track_count": len(self._song.tracks)
            }
        except Exception as e:
            self.log_message("Error deleting track: " + str(e))
            raise

    def _get_arrangement_clips(self, track_index):
        """Get arrangement clips for a track"""
        try:
            track = self._get_track(track_index)
            clips = []
            if hasattr(track, 'arrangement_clips'):
                for clip in track.arrangement_clips:
                    is_audio = clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False
                    clip_info = {
                        "name": clip.name,
                        "start_time": clip.start_time if hasattr(clip, 'start_time') else 0,
                        "end_time": clip.end_time if hasattr(clip, 'end_time') else 0,
                        "length": clip.length,
                        "is_midi_clip": clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else False,
                        "is_audio_clip": is_audio,
                        "color_index": getattr(clip, "color_index", None),
                    }
                    if is_audio and hasattr(clip, 'file_path'):
                        clip_info["file_path"] = clip.file_path
                    clips.append(clip_info)
            return {
                "track_index": track_index,
                "track_name": track.name,
                "arrangement_clip_count": len(clips),
                "clips": clips
            }
        except Exception as e:
            self.log_message("Error getting arrangement clips: " + str(e))
            raise

    def _get_full_arrangement(self):
        """Get arrangement clips for all tracks at once"""
        try:
            tracks_data = []
            all_tracks = list(self._song.tracks)
            for i, track in enumerate(all_tracks):
                clips = []
                if not track.is_foldable:
                    for clip in track.arrangement_clips:
                        is_audio = clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False
                        clip_info = {
                            "name": clip.name,
                            "start_time": clip.start_time if hasattr(clip, 'start_time') else 0,
                            "end_time": clip.end_time if hasattr(clip, 'end_time') else 0,
                            "length": clip.length,
                            "is_midi_clip": clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else False,
                            "is_audio_clip": is_audio,
                        }
                        if is_audio and hasattr(clip, 'file_path'):
                            clip_info["file_path"] = clip.file_path
                        clips.append(clip_info)
                if clips:
                    tracks_data.append({
                        "track_index": i,
                        "track_name": track.name,
                        "clips": clips
                    })

            # Scene info
            scenes = []
            for i, scene in enumerate(self._song.scenes):
                scenes.append({"index": i, "name": scene.name})

            return {
                "tempo": self._song.tempo,
                "time_signature": "{0}/{1}".format(
                    self._song.signature_numerator,
                    self._song.signature_denominator),
                "song_length": self._song.song_length,
                "tracks_with_clips": tracks_data,
                "scenes": scenes
            }
        except Exception as e:
            self.log_message("Error getting full arrangement: " + str(e))
            raise

    def _delete_scene(self, scene_index):
        """Delete a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene_name = self._song.scenes[scene_index].name
            self._song.delete_scene(scene_index)
            return {
                "deleted_scene": scene_name,
                "scene_count": len(self._song.scenes)
            }
        except Exception as e:
            self.log_message("Error deleting scene: " + str(e))
            raise

    def _record_arrangement(self, sections, start_time=0.0):
        """Record session clips into arrangement by firing scenes at timed intervals.
        sections: list of {"scene_index": int, "bars": int}
        start_time: arrangement position (in beats) to begin recording from. Default 0.

        Uses polling with fire-and-forget scene fires (no round-trip wait).
        clip_trigger_quantization=4 (1 Bar) snaps fires to bar boundaries.
        Fires scene 2 beats before target so quantization lands on the right bar."""
        import time as time_module

        tempo = self._song.tempo
        beats_per_bar = self._song.signature_numerator
        seconds_per_beat = 60.0 / tempo

        result_holder = {"result": None, "error": None, "done": False}
        saved_quantization = [0]
        cancelled = [False]

        def do_on_main(fn):
            """Execute fn on main thread and wait for completion."""
            done_event = threading.Event()
            error_holder = [None]
            def task():
                try:
                    fn()
                except Exception as e:
                    error_holder[0] = e
                done_event.set()
            self.schedule_message(0, task)
            done_event.wait(timeout=5.0)
            if error_holder[0]:
                raise error_holder[0]

        def fire_and_forget(fn):
            """Schedule fn on main thread without waiting. For time-critical fires."""
            def guarded():
                if not cancelled[0]:
                    fn()
            self.schedule_message(0, guarded)

        def recording_thread():
            try:
                # Save and set clip trigger quantization to 1 Bar
                def set_quantization():
                    saved_quantization[0] = self._song.clip_trigger_quantization
                    self._song.clip_trigger_quantization = 4  # 1 Bar
                do_on_main(set_quantization)

                # Disarm all tracks to prevent stray MIDI recording
                def disarm_all():
                    for track in self._song.tracks:
                        if track.can_be_armed and track.arm:
                            track.arm = False
                do_on_main(disarm_all)

                # Stop playback and prepare
                do_on_main(lambda: self._song.stop_playing() if self._song.is_playing else None)
                time_module.sleep(0.1)
                do_on_main(lambda: setattr(self._song, 'back_to_arranger', True))
                time_module.sleep(0.05)

                # Seek to start_time
                def seek_start():
                    self._song.current_song_time = start_time
                    for _ in range(5):
                        if abs(self._song.current_song_time - start_time) < 0.5:
                            break
                        self._song.current_song_time = start_time
                do_on_main(seek_start)
                time_module.sleep(0.05)

                # Enable recording
                do_on_main(lambda: setattr(self._song, 'record_mode', 1))
                time_module.sleep(0.05)

                total_bars = 0
                recorded_sections = []
                scene_count = len(self._song.scenes)

                for i, section in enumerate(sections):
                    si = section.get("scene_index", 0)
                    bars = section.get("bars", 8)

                    if si < 0 or si >= scene_count:
                        self.log_message("Skipping invalid scene index: {0}".format(si))
                        continue

                    # Fire this scene
                    scene_name = [""]
                    if i == 0:
                        # First scene: fire immediately
                        def fire_first(idx=si):
                            self._song.scenes[idx].fire()
                            scene_name[0] = self._song.scenes[idx].name
                        do_on_main(fire_first)
                    else:
                        # Already fired by previous iteration, just get name
                        def get_name(idx=si):
                            scene_name[0] = self._song.scenes[idx].name
                        do_on_main(get_name)

                    self.log_message("Recording section {0}: scene {1} ({2}) for {3} bars".format(
                        i + 1, si, scene_name[0], bars))

                    target_beat = start_time + (total_bars + bars) * beats_per_bar
                    next_section = sections[i + 1] if i + 1 < len(sections) else None
                    next_fired = [False]

                    # Fire next scene 2 beats before target.
                    # With 1-bar quantization, this is within the last bar before
                    # the target boundary, so it snaps to the target beat.
                    # Use fire_and_forget (no round-trip wait) to minimize latency.
                    fire_beat = target_beat - 2.0 if next_section else None

                    while True:
                        # Read current time — need do_on_main for this
                        current_holder = [0.0]
                        def get_time():
                            current_holder[0] = self._song.current_song_time
                        do_on_main(get_time)
                        current = current_holder[0]

                        # Fire next scene (fire-and-forget, no waiting)
                        if fire_beat is not None and not next_fired[0] and current >= fire_beat:
                            next_si = next_section.get("scene_index", 0)
                            def fire_next(idx=next_si):
                                self._song.scenes[idx].fire()
                            fire_and_forget(fire_next)
                            next_fired[0] = True
                            self.log_message("Fired next scene {0} at beat {1:.1f} (target {2})".format(
                                next_si, current, target_beat))

                        if current >= target_beat - 0.5:
                            break

                        remaining_seconds = (target_beat - current) * seconds_per_beat
                        if remaining_seconds > 2.0:
                            time_module.sleep(remaining_seconds - 1.5)
                        else:
                            time_module.sleep(0.02)

                    recorded_sections.append({
                        "scene_index": si,
                        "scene_name": scene_name[0],
                        "bars": bars,
                        "start_bar": total_bars + 1,
                        "end_bar": total_bars + bars
                    })
                    total_bars += bars

                # Stop recording
                do_on_main(lambda: setattr(self._song, 'record_mode', 0))
                time_module.sleep(0.05)
                do_on_main(lambda: self._song.stop_playing())
                time_module.sleep(0.1)

                # Restore quantization and return to arrangement
                def cleanup():
                    self._song.clip_trigger_quantization = saved_quantization[0]
                    self._song.stop_all_clips()
                    self._song.back_to_arranger = True
                    self._song.current_song_time = 0.0
                do_on_main(cleanup)

                result_holder["result"] = {
                    "total_bars": total_bars,
                    "total_beats": total_bars * beats_per_bar,
                    "sections": recorded_sections,
                    "tempo": tempo
                }
            except Exception as e:
                cancelled[0] = True
                try:
                    do_on_main(lambda: setattr(self._song, 'record_mode', 0))
                    do_on_main(lambda: self._song.stop_playing())
                    do_on_main(lambda: setattr(self._song, 'clip_trigger_quantization', saved_quantization[0]))
                except:
                    pass
                self.log_message("Error recording arrangement: " + str(e))
                result_holder["error"] = e
            finally:
                result_holder["done"] = True

        rec_thread = threading.Thread(target=recording_thread)
        rec_thread.daemon = True
        rec_thread.start()

        total_duration = sum(s.get("bars", 8) for s in sections) * beats_per_bar * seconds_per_beat
        rec_thread.join(timeout=total_duration + 30)

        if result_holder["error"]:
            raise result_holder["error"]
        if not result_holder["done"]:
            raise Exception("Recording timed out")
        return result_holder["result"]

    def _delete_device(self, track_index, device_index):
        """Delete a device from a track"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device_name = track.devices[device_index].name
            track.delete_device(device_index)
            return {
                "deleted_device": device_name,
                "device_count": len(track.devices)
            }
        except Exception as e:
            self.log_message("Error deleting device: " + str(e))
            raise

    def _duplicate_track(self, track_index):
        """Duplicate a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track_name = self._song.tracks[track_index].name
            self._song.duplicate_track(track_index)
            new_track = self._song.tracks[track_index + 1]
            return {
                "original_track": track_name,
                "new_track_index": track_index + 1,
                "new_track_name": new_track.name,
                "track_count": len(self._song.tracks)
            }
        except Exception as e:
            self.log_message("Error duplicating track: " + str(e))
            raise

    def _set_clip_loop(self, track_index, clip_index, loop_start, loop_end, looping):
        """Set clip loop settings"""
        try:
            track = self._song.tracks[track_index]
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if looping is not None:
                clip.looping = bool(looping)
            if loop_start is not None:
                clip.loop_start = float(loop_start)
            if loop_end is not None:
                clip.loop_end = float(loop_end)
            return {
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "length": clip.length
            }
        except Exception as e:
            self.log_message("Error setting clip loop: " + str(e))
            raise

    def _get_clip_notes(self, track_index, clip_index):
        """Get all notes from a MIDI clip"""
        try:
            track = self._song.tracks[track_index]
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not clip.is_midi_clip:
                raise Exception("Not a MIDI clip")
            notes = clip.get_notes_extended(from_pitch=0, pitch_span=128, from_time=0, time_span=clip.length)
            note_list = []
            for note in notes:
                note_list.append({
                    "pitch": note.pitch,
                    "start_time": note.start_time,
                    "duration": note.duration,
                    "velocity": note.velocity,
                    "mute": note.mute
                })
            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "clip_name": clip.name,
                "length": clip.length,
                "note_count": len(note_list),
                "notes": note_list
            }
        except Exception as e:
            self.log_message("Error getting clip notes: " + str(e))
            raise

    def _get_arrangement_clip_notes(self, track_index, arrangement_clip_index):
        """Get all notes from a MIDI clip in the arrangement view (by index in track.arrangement_clips)."""
        try:
            track = self._song.tracks[track_index]
            if not hasattr(track, 'arrangement_clips'):
                raise Exception("Track has no arrangement_clips")
            clips = list(track.arrangement_clips)
            if arrangement_clip_index < 0 or arrangement_clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range")
            clip = clips[arrangement_clip_index]
            if not clip.is_midi_clip:
                raise Exception("Not a MIDI clip")
            notes = clip.get_notes_extended(from_pitch=0, pitch_span=128, from_time=0, time_span=clip.length)
            note_list = []
            for note in notes:
                note_list.append({
                    "pitch": note.pitch,
                    "start_time": note.start_time,
                    "duration": note.duration,
                    "velocity": note.velocity,
                    "mute": note.mute,
                })
            return {
                "track_index": track_index,
                "arrangement_clip_index": arrangement_clip_index,
                "clip_name": clip.name,
                "start_time": float(clip.start_time) if hasattr(clip, 'start_time') else 0,
                "length": clip.length,
                "note_count": len(note_list),
                "notes": note_list,
            }
        except Exception as e:
            self.log_message("Error getting arrangement clip notes: " + str(e))
            raise

    def _delete_arrangement_clip(self, track_index, arrangement_clip_index):
        """Delete an arrangement clip by track + index in track.arrangement_clips."""
        try:
            track = self._song.tracks[track_index]
            if not hasattr(track, 'arrangement_clips'):
                raise Exception("Track has no arrangement_clips")
            clips = list(track.arrangement_clips)
            if arrangement_clip_index < 0 or arrangement_clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range")
            clip = clips[arrangement_clip_index]
            start = float(clip.start_time) if hasattr(clip, 'start_time') else 0.0
            end = float(clip.end_time) if hasattr(clip, 'end_time') else start + clip.length
            # Live exposes Track.delete_clip(clip) on most versions; fall back to time range.
            if hasattr(track, 'delete_clip'):
                track.delete_clip(clip)
            elif hasattr(self._song, 'delete_arrangement_clip'):
                self._song.delete_arrangement_clip(track, start, end)
            else:
                raise Exception("No delete arrangement clip method available on this Live version")
            return {
                "track_index": track_index,
                "deleted_index": arrangement_clip_index,
                "remaining_count": len(track.arrangement_clips),
            }
        except Exception as e:
            self.log_message("Error deleting arrangement clip: " + str(e))
            raise

    def _set_track_arm(self, track_index, arm):
        """Set track arm state"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            track = self._song.tracks[track_index]
            if not track.can_be_armed:
                raise Exception("Track cannot be armed")
            track.arm = bool(arm)
            return {
                "track_index": track_index,
                "track_name": track.name,
                "arm": track.arm
            }
        except Exception as e:
            self.log_message("Error setting track arm: " + str(e))
            raise

    def _set_send_level(self, track_index, send_index, value):
        """Set send level for a track"""
        try:
            track = self._get_track(track_index)
            sends = track.mixer_device.sends
            if send_index < 0 or send_index >= len(sends):
                raise IndexError("Send index out of range (track has {0} sends)".format(len(sends)))
            send = sends[send_index]
            send.value = max(send.min, min(send.max, send.min + float(value) * (send.max - send.min)))
            return {
                "track_index": track_index,
                "send_index": send_index,
                "value": value,
                "actual_value": send.value
            }
        except Exception as e:
            self.log_message("Error setting send level: " + str(e))
            raise

    def _set_time_signature(self, numerator, denominator):
        """Set the song time signature"""
        try:
            self._song.signature_numerator = int(numerator)
            self._song.signature_denominator = int(denominator)
            return {
                "numerator": self._song.signature_numerator,
                "denominator": self._song.signature_denominator
            }
        except Exception as e:
            self.log_message("Error setting time signature: " + str(e))
            raise

    def _set_metronome(self, on):
        """Set metronome on/off"""
        try:
            self._song.metronome = bool(on)
            return {"metronome": self._song.metronome}
        except Exception as e:
            self.log_message("Error setting metronome: " + str(e))
            raise

    def _set_clip_envelope(self, track_index, clip_index, device_index, parameter_index, points):
        """Set automation envelope points for a parameter in a clip.
        points: list of {"time": float, "value": float} (value is normalized 0-1)"""
        try:
            track = self._song.tracks[track_index]
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip

            device = track.devices[device_index]
            param = device.parameters[parameter_index]

            # Try to get existing envelope, or create one
            envelope = clip.automation_envelope(param)
            if envelope is None:
                # Create a new envelope for this parameter
                envelope = clip.create_automation_envelope(param)
            if envelope is None:
                raise Exception("Could not create automation envelope for parameter")

            # Sort points by time and interpolate smooth ramps between them
            sorted_points = sorted(points, key=lambda p: float(p.get("time", 0)))
            step_size = 0.25  # beats per interpolation step
            for i in range(len(sorted_points) - 1):
                t0 = float(sorted_points[i].get("time", 0))
                v0 = float(sorted_points[i].get("value", 0))
                t1 = float(sorted_points[i + 1].get("time", 0))
                v1 = float(sorted_points[i + 1].get("value", 0))
                segment_duration = t1 - t0
                num_steps = max(1, int(segment_duration / step_size))
                for s in range(num_steps):
                    frac = s / float(num_steps)
                    t = t0 + frac * segment_duration
                    v = v0 + frac * (v1 - v0)
                    actual = param.min + v * (param.max - param.min)
                    envelope.insert_step(t, step_size, actual)
            # Last point holds for 1 beat
            if sorted_points:
                last = sorted_points[-1]
                t = float(last.get("time", 0))
                v = float(last.get("value", 0))
                actual = param.min + v * (param.max - param.min)
                envelope.insert_step(t, 1.0, actual)

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "device_index": device_index,
                "parameter_index": parameter_index,
                "parameter_name": param.name,
                "points_set": len(points)
            }
        except Exception as e:
            self.log_message("Error setting clip envelope: " + str(e))
            raise

    def _get_clip_envelope(self, track_index, clip_index, device_index, parameter_index):
        """Read automation envelope data for a parameter in a clip."""
        try:
            track = self._song.tracks[track_index]
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip

            device = track.devices[device_index]
            param = device.parameters[parameter_index]

            envelope = clip.automation_envelope(param)
            if envelope is None:
                return {
                    "track_index": track_index,
                    "clip_index": clip_index,
                    "parameter_name": param.name,
                    "has_envelope": False,
                    "points": []
                }

            # Read envelope value at regular intervals across the clip
            clip_length = clip.length
            num_samples = min(int(clip_length), 64)  # Sample up to 64 points
            step = clip_length / num_samples if num_samples > 0 else 1.0
            points = []
            for i in range(num_samples):
                t = i * step
                val = envelope.value_at_time(t)
                # Normalize to 0-1
                param_range = param.max - param.min
                normalized = (val - param.min) / param_range if param_range > 0 else 0
                points.append({"time": round(t, 3), "value": round(normalized, 4)})

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": param.name,
                "has_envelope": True,
                "points": points
            }
        except Exception as e:
            self.log_message("Error getting clip envelope: " + str(e))
            raise

    def _clear_clip_envelope(self, track_index, clip_index, device_index, parameter_index):
        """Clear automation envelope for a parameter in a clip"""
        try:
            track = self._song.tracks[track_index]
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip

            device = track.devices[device_index]
            param = device.parameters[parameter_index]

            clip.clear_envelope(param)

            return {
                "track_index": track_index,
                "clip_index": clip_index,
                "parameter_name": param.name,
                "cleared": True
            }
        except Exception as e:
            self.log_message("Error clearing clip envelope: " + str(e))
            raise

    def _undo(self):
        """Undo the last action"""
        try:
            self._song.undo()
            return {"undone": True}
        except Exception as e:
            self.log_message("Error undoing: " + str(e))
            raise

    def _redo(self):
        """Redo the last undone action"""
        try:
            self._song.redo()
            return {"redone": True}
        except Exception as e:
            self.log_message("Error redoing: " + str(e))
            raise

    def _get_device_parameters(self, track_index, device_index):
        """Get all parameters of a device on a track"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            parameters = []
            for i, p in enumerate(device.parameters):
                norm_val = 0
                if (p.max - p.min) != 0:
                    norm_val = (p.value - p.min) / (p.max - p.min)
                entry = {
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "normalized_value": norm_val,
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "is_enabled": p.is_enabled
                }
                # What Live's UI shows ("-6.0 dB", "1/4", "Saw D") and, for menus, every option in order
                try:
                    entry["display"] = p.str_for_value(p.value)
                except Exception:
                    pass
                if p.is_quantized:
                    try:
                        entry["items"] = list(p.value_items)
                    except Exception:
                        pass
                parameters.append(entry)
            return {
                "track_index": track_index,
                "track_name": track.name,
                "device_index": device_index,
                "device_name": device.name,
                "parameters": parameters
            }
        except Exception as e:
            self.log_message("Error getting device parameters: " + str(e))
            raise

    def _set_device_parameter(self, track_index, device_index, parameter_index, value):
        """Set a single device parameter using a normalized value (0.0 to 1.0)"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if parameter_index < 0 or parameter_index >= len(device.parameters):
                raise IndexError("Parameter index out of range")
            parameter = device.parameters[parameter_index]
            if value < 0.0 or value > 1.0:
                raise ValueError("Normalized value must be between 0.0 and 1.0")
            actual_value = parameter.min + value * (parameter.max - parameter.min)
            parameter.value = actual_value
            return {
                "parameter_name": parameter.name,
                "value": parameter.value,
                "normalized_value": value
            }
        except Exception as e:
            self.log_message("Error setting device parameter: " + str(e))
            raise

    def _batch_set_device_parameters(self, track_index, device_index, parameter_indices, values):
        """Set multiple device parameters at once using normalized values (0.0 to 1.0)"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if len(parameter_indices) != len(values):
                raise ValueError("parameter_indices and values must have the same length")
            updated = []
            for i in range(len(parameter_indices)):
                p_idx = parameter_indices[i]
                val = values[i]
                if p_idx < 0 or p_idx >= len(device.parameters):
                    continue
                if val < 0.0 or val > 1.0:
                    continue
                param = device.parameters[p_idx]
                actual_val = param.min + val * (param.max - param.min)
                param.value = actual_val
                updated.append({
                    "index": p_idx,
                    "name": param.name,
                    "value": param.value,
                    "normalized_value": val
                })
            return {
                "updated_count": len(updated),
                "parameters": updated
            }
        except Exception as e:
            self.log_message("Error batch setting device parameters: " + str(e))
            raise

    def _create_midi_track(self, index):
        """Create a new MIDI track at the specified index"""
        try:
            # Create the track
            self._song.create_midi_track(index)
            
            # Get the new track
            new_track_index = len(self._song.tracks) - 1 if index == -1 else index
            new_track = self._song.tracks[new_track_index]
            
            result = {
                "index": new_track_index,
                "name": new_track.name
            }
            return result
        except Exception as e:
            self.log_message("Error creating MIDI track: " + str(e))
            raise
    
    
    def _set_track_name(self, track_index, name):
        """Set the name of a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            # Set the name
            track = self._song.tracks[track_index]
            track.name = name
            
            result = {
                "name": track.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting track name: " + str(e))
            raise
    
    def _create_clip(self, track_index, clip_index, length):
        """Create a new MIDI clip in the specified track and clip slot"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            # Check if the clip slot already has a clip
            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")
            
            # Create the clip
            clip_slot.create_clip(length)
            
            result = {
                "name": clip_slot.clip.name,
                "length": clip_slot.clip.length
            }
            return result
        except Exception as e:
            self.log_message("Error creating clip: " + str(e))
            raise
    
    def _create_arrangement_midi_clip(self, track_index, time, length, notes=None):
        """Create a MIDI clip in the arrangement view at a given position with optional notes.

        Uses Live 11+ Track.create_midi_clip(start_time, end_time) API.
        notes: optional list of note dicts to seed the clip with.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if not track.has_midi_input:
                raise Exception("Track {0} is not a MIDI track".format(track_index))

            if not hasattr(track, 'create_midi_clip'):
                raise Exception("Live version does not support Track.create_midi_clip; need Live 11+")

            start = float(time)
            length_val = float(length)
            # Live's Track.create_midi_clip takes (start_time, length) in beats,
            # not (start_time, end_time) despite some docs suggesting otherwise.
            clip = track.create_midi_clip(start, length_val)

            note_count = 0
            if notes and clip is not None:
                live_notes = []
                for n in notes:
                    pitch = n.get("pitch", 60)
                    start_time = n.get("start_time", 0.0)
                    duration = n.get("duration", 0.25)
                    velocity = n.get("velocity", 100)
                    mute = n.get("mute", False)
                    live_notes.append((pitch, start_time, duration, velocity, mute))
                clip.set_notes(tuple(live_notes))
                note_count = len(live_notes)

            # Find this clip's index in arrangement_clips so caller can refer to it later
            arrangement_index = -1
            try:
                for i, ac in enumerate(track.arrangement_clips):
                    if abs(float(ac.start_time) - start) < 0.001:
                        arrangement_index = i
                        break
            except Exception:
                pass

            return {
                "track_index": track_index,
                "start_time": start,
                "length": float(length),
                "note_count": note_count,
                "arrangement_clip_index": arrangement_index,
                "name": clip.name if clip else "",
            }
        except Exception as e:
            self.log_message("Error creating arrangement MIDI clip: " + str(e))
            raise

    def _create_arrangement_audio_clips_batch(self, track_index, file_path, times, length=None, start_offset=None):
        """The same sample at several beat positions in one round trip (repeated hits)."""
        results = []
        for t in times:
            try:
                self._create_arrangement_audio_clip(track_index, file_path, float(t), length, start_offset)
                results.append({"time": float(t), "ok": True})
            except Exception as e:
                results.append({"time": float(t), "ok": False, "error": str(e)})
        return {"track_index": track_index, "file_path": file_path,
                "placed_count": sum(1 for r in results if r["ok"]),
                "failed_count": sum(1 for r in results if not r["ok"]), "results": results}

    def _create_arrangement_audio_clip(self, track_index, file_path, time, length=None, start_offset=None):
        """Create an audio clip from a file path in the arrangement view at a given position.

        Uses Live 11+ Track.create_audio_clip(file_path, position) API.
        length is optional: the clip loops its first `length` beats (Live 12 refuses end_time on
        a fresh arrangement audio clip, so the loop end is trimmed instead); a following clip
        truncates the region.
        start_offset (beats) skips the head of the sample (a whoosh before the hit): the
        clip's start marker is advanced by that much.
        """
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if not track.has_audio_input:
                raise Exception("Track {0} is not an audio track".format(track_index))

            if not hasattr(track, 'create_audio_clip'):
                raise Exception("Live version does not support Track.create_audio_clip; need Live 11+")

            # Live 11+ API: create_audio_clip(file_path, position) returns the new Clip
            clip = track.create_audio_clip(file_path, float(time))

            length_note = ""
            if length is not None and clip is not None:
                try:
                    clip.end_time = float(time) + float(length)
                except Exception as le:
                    try:                                    # end_time may be read-only: trim the loop instead
                        clip.looping = True
                        clip.loop_end = clip.start_marker + float(length)
                    except Exception as le2:
                        length_note = "length not applied: %s / %s" % (le, le2)
                        self.log_message(length_note)
            if start_offset is not None and clip is not None:
                try:
                    clip.start_marker = clip.start_marker + float(start_offset)
                except Exception as oe:
                    self.log_message("start_offset not applied: " + str(oe))

            result = {
                "track_index": track_index,
                "file_path": file_path,
                "start_time": clip.start_time if clip else float(time),
                "length": clip.length if clip else 0,
                "start_marker": clip.start_marker if clip else None,
                "name": clip.name if clip else "",
                "note": length_note,
            }
            return result
        except Exception as e:
            self.log_message("Error creating arrangement audio clip: " + str(e))
            raise

    def _add_notes_to_clip(self, track_index, clip_index, notes):
        """Add MIDI notes to a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip = clip_slot.clip
            
            # Convert note data to Live's format
            live_notes = []
            for note in notes:
                pitch = note.get("pitch", 60)
                start_time = note.get("start_time", 0.0)
                duration = note.get("duration", 0.25)
                velocity = note.get("velocity", 100)
                mute = note.get("mute", False)
                
                live_notes.append((pitch, start_time, duration, velocity, mute))
            
            # Add the notes
            clip.set_notes(tuple(live_notes))
            
            result = {
                "note_count": len(notes)
            }
            return result
        except Exception as e:
            self.log_message("Error adding notes to clip: " + str(e))
            raise
    
    def _set_clip_name(self, track_index, clip_index, name, aci=None):
        """Set the name of a clip: session slot, or an arrangement clip when aci is given"""
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            clip.name = name
            
            result = {
                "name": clip.name
            }
            return result
        except Exception as e:
            self.log_message("Error setting clip name: " + str(e))
            raise
    
    def _set_tempo(self, tempo):
        """Set the tempo of the session"""
        try:
            self._song.tempo = tempo
            
            result = {
                "tempo": self._song.tempo
            }
            return result
        except Exception as e:
            self.log_message("Error setting tempo: " + str(e))
            raise
    
    def _fire_clip(self, track_index, clip_index):
        """Fire a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            
            clip_slot.fire()
            
            result = {
                "fired": True
            }
            return result
        except Exception as e:
            self.log_message("Error firing clip: " + str(e))
            raise
    
    def _stop_clip(self, track_index, clip_index):
        """Stop a clip"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            
            clip_slot = track.clip_slots[clip_index]
            
            clip_slot.stop()
            
            result = {
                "stopped": True
            }
            return result
        except Exception as e:
            self.log_message("Error stopping clip: " + str(e))
            raise
    
    
    def _play_arrangement(self, time=None):
        """Stop session clips, return to arrangement, optionally seek, and play."""
        try:
            self._song.stop_all_clips()
            self._song.back_to_arranger = False      # False = arrangement plays (True = session overrides it)
            # start_playing() plays from the insert marker, and a seek made while stopped lands a
            # moment later, so start first and seek while playing (that lands at once)
            self._song.start_playing()
            if time is not None:
                self._song.current_song_time = float(time)
            return {
                "playing": True,
                "position": self._song.current_song_time
            }
        except Exception as e:
            self.log_message("Error playing arrangement: " + str(e))
            raise

    def _start_playback(self):
        """Start playing the session"""
        try:
            self._song.start_playing()

            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error starting playback: " + str(e))
            raise
    
    def _stop_playback(self):
        """Stop playing the session"""
        try:
            self._song.stop_playing()
            
            result = {
                "playing": self._song.is_playing
            }
            return result
        except Exception as e:
            self.log_message("Error stopping playback: " + str(e))
            raise
    
    def _get_browser_item(self, uri, path):
        """Get a browser item by URI or path"""
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            result = {
                "uri": uri,
                "path": path,
                "found": False
            }
            
            # Try to find by URI first if provided
            if uri:
                item = self._find_browser_item_by_uri(app.browser, uri)
                if item:
                    result["found"] = True
                    result["item"] = {
                        "name": item.name,
                        "is_folder": item.is_folder,
                        "is_device": item.is_device,
                        "is_loadable": item.is_loadable,
                        "uri": item.uri
                    }
                    return result
            
            # If URI not provided or not found, try by path
            if path:
                # Parse the path and navigate to the specified item
                path_parts = path.split("/")
                
                # Determine the root based on the first part
                current_item = None
                if path_parts[0].lower() == "nstruments":
                    current_item = app.browser.instruments
                elif path_parts[0].lower() == "sounds":
                    current_item = app.browser.sounds
                elif path_parts[0].lower() == "drums":
                    current_item = app.browser.drums
                elif path_parts[0].lower() == "audio_effects":
                    current_item = app.browser.audio_effects
                elif path_parts[0].lower() == "midi_effects":
                    current_item = app.browser.midi_effects
                else:
                    # Default to instruments if not specified
                    current_item = app.browser.instruments
                    # Don't skip the first part in this case
                    path_parts = ["instruments"] + path_parts
                
                # Navigate through the path
                for i in range(1, len(path_parts)):
                    part = path_parts[i]
                    if not part:  # Skip empty parts
                        continue
                    
                    found = False
                    for child in current_item.children:
                        if child.name.lower() == part.lower():
                            current_item = child
                            found = True
                            break
                    
                    if not found:
                        result["error"] = "Path part '{0}' not found".format(part)
                        return result
                
                # Found the item
                result["found"] = True
                result["item"] = {
                    "name": current_item.name,
                    "is_folder": current_item.is_folder,
                    "is_device": current_item.is_device,
                    "is_loadable": current_item.is_loadable,
                    "uri": current_item.uri
                }
            
            return result
        except Exception as e:
            self.log_message("Error getting browser item: " + str(e))
            self.log_message(traceback.format_exc())
            raise   
    
    
    
    def _load_browser_item(self, track_index, item_uri, clip_index=None):
        """Load a browser item onto a track by its URI. Use -1 for master track.
        If clip_index is provided, selects that clip slot before loading (needed for .alc clips)."""
        try:
            track = self._get_track(track_index)

            # Access the application's browser instance instead of creating a new one
            app = self.application()

            # Find the browser item by URI
            item = self._find_browser_item_by_uri(app.browser, item_uri)

            if not item:
                raise ValueError("Browser item with URI '{0}' not found".format(item_uri))

            # Select the track
            self._song.view.selected_track = track

            # If clip_index provided, select that clip slot so .alc clips land there
            if clip_index is not None and hasattr(track, 'clip_slots'):
                if clip_index < len(track.clip_slots):
                    self._song.view.highlighted_clip_slot = track.clip_slots[clip_index]

            # Load the item
            app.browser.load_item(item)
            
            result = {
                "loaded": True,
                "item_name": item.name,
                "track_name": track.name,
                "uri": item_uri
            }
            return result
        except Exception as e:
            self.log_message("Error loading browser item: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def _find_browser_item_by_uri(self, browser_or_item, uri, max_depth=10, current_depth=0):
        """Find a browser item by its URI"""
        try:
            # Check if this is the item we're looking for
            if hasattr(browser_or_item, 'uri') and browser_or_item.uri == uri:
                return browser_or_item
            
            # Stop recursion if we've reached max depth
            if current_depth >= max_depth:
                return None
            
            # Check if this is a browser with root categories
            if hasattr(browser_or_item, 'instruments'):
                # Check all main categories
                categories = [
                    browser_or_item.instruments,
                    browser_or_item.sounds,
                    browser_or_item.drums,
                    browser_or_item.audio_effects,
                    browser_or_item.midi_effects,
                ]
                # Add optional categories that may not exist on all versions
                for attr in ['clips', 'samples', 'packs', 'user_library', 'current_project', 'max_for_live']:
                    if hasattr(browser_or_item, attr):
                        cat = getattr(browser_or_item, attr)
                        if cat is not None:
                            categories.append(cat)
                
                for category in categories:
                    item = self._find_browser_item_by_uri(category, uri, max_depth, current_depth + 1)
                    if item:
                        return item
                
                return None
            
            # Check if this item has children
            if hasattr(browser_or_item, 'children') and browser_or_item.children:
                for child in browser_or_item.children:
                    item = self._find_browser_item_by_uri(child, uri, max_depth, current_depth + 1)
                    if item:
                        return item
            
            return None
        except Exception as e:
            self.log_message("Error finding browser item by URI: {0}".format(str(e)))
            return None
    
    # Helper methods
    
    # ------------------------------------------------------------------
    # Clip editing, device bypass, return tracks, drum pads
    # (ported from the missing-features branch: the subset an agent
    # actually reaches for; see MISSING_FEATURES.md for the rest)
    # ------------------------------------------------------------------
    def _session_clip(self, track_index, clip_index, midi=None, arrangement_clip_index=None):
        """A clip: session slot `clip_index`, or `track.arrangement_clips[arrangement_clip_index]`
        when that is given (audio clips can only be created in the arrangement over the socket).
        `midi` True/False asserts the clip type."""
        track = self._get_track(track_index)
        if arrangement_clip_index is not None:
            clips = list(track.arrangement_clips)
            if arrangement_clip_index < 0 or arrangement_clip_index >= len(clips):
                raise IndexError("Arrangement clip index out of range")
            clip = clips[arrangement_clip_index]
        else:
            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")
            slot = track.clip_slots[clip_index]
            if not slot.has_clip:
                raise Exception("No clip in slot {0} of track {1}".format(clip_index, track_index))
            clip = slot.clip
        if midi is True and not clip.is_midi_clip:
            raise Exception("Not a MIDI clip")
        if midi is False and not clip.is_audio_clip:
            raise Exception("Not an audio clip")
        return clip

    def _remove_notes(self, track_index, clip_index, from_pitch, pitch_span, from_time, time_span, aci=None):
        """Remove the notes inside a pitch/time window. time_span < 0 = to the end of the clip."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=True, arrangement_clip_index=aci)
            if time_span is None or time_span < 0:
                time_span = max(clip.length - from_time, 0.0)
            before = len(clip.get_notes_extended(0, 128, 0.0, clip.length))
            clip.remove_notes_extended(from_pitch, pitch_span, from_time, time_span)
            after = len(clip.get_notes_extended(0, 128, 0.0, clip.length))
            return {"removed": before - after, "remaining": after}
        except Exception as e:
            self.log_message("Error removing notes: " + str(e))
            raise

    def _quantize_clip(self, track_index, clip_index, grid, strength, aci=None):
        """clip.quantize(grid, strength); grid is Live's RecordingQuantization enum, verified
        on Live 12: 1=1/4, 2=1/8, 3=1/8+1/8T, 4=1/8T, 5=1/16, 6=1/16+1/16T, 7=1/16T, 8=1/32."""
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            clip.quantize(int(grid), float(strength))
            return {"quantized": True, "grid": int(grid), "strength": float(strength)}
        except Exception as e:
            self.log_message("Error quantizing clip: " + str(e))
            raise

    def _duplicate_clip_loop(self, track_index, clip_index, aci=None):
        """Double the loop and copy its contents into the new half."""
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            clip.duplicate_loop()
            return {"length": clip.length, "loop_start": clip.loop_start, "loop_end": clip.loop_end}
        except Exception as e:
            self.log_message("Error duplicating clip loop: " + str(e))
            raise

    def _duplicate_region(self, track_index, clip_index, region_start, region_length, destination_time,
                          pitch=-1, transposition_amount=0, aci=None):
        """Copy [region_start, +region_length) to destination_time; pitch -1 = all pitches."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=True, arrangement_clip_index=aci)
            clip.duplicate_region(float(region_start), float(region_length), float(destination_time),
                                  int(pitch), int(transposition_amount))
            return {"duplicated": True, "length": clip.length}
        except Exception as e:
            self.log_message("Error duplicating region: " + str(e))
            raise

    def _set_device_enabled(self, track_index, device_index, enabled):
        """Bypass / re-enable a device through its 'Device On' parameter (works for master and returns too)."""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            for param in device.parameters:
                if param.name == "Device On":
                    param.value = 1.0 if enabled else 0.0
                    return {"enabled": bool(enabled), "device_name": device.name}
            raise Exception("Device has no 'Device On' parameter")
        except Exception as e:
            self.log_message("Error setting device enabled: " + str(e))
            raise

    def _create_return_track(self):
        try:
            self._song.create_return_track()
            return {"return_track_count": len(self._song.return_tracks), "name": self._song.return_tracks[-1].name}
        except Exception as e:
            self.log_message("Error creating return track: " + str(e))
            raise

    def _delete_return_track(self, index):
        try:
            if index < 0 or index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            self._song.delete_return_track(index)
            return {"return_track_count": len(self._song.return_tracks)}
        except Exception as e:
            self.log_message("Error deleting return track: " + str(e))
            raise

    def _stop_all_clips(self, quantized=True):
        try:
            self._song.stop_all_clips(bool(quantized))
            return {"stopped": True}
        except Exception as e:
            self.log_message("Error stopping all clips: " + str(e))
            raise

    def _get_drum_pads(self, track_index, device_index):
        """The filled pads of a Drum Rack: note number, pad name, and the device on the pad."""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if not hasattr(device, "drum_pads"):
                raise Exception("Device '{0}' is not a Drum Rack".format(device.name))
            pads = []
            for pad in device.drum_pads:
                if not pad.chains:
                    continue
                info = {"note": pad.note, "name": pad.name, "mute": pad.mute, "solo": pad.solo}
                if pad.chains[0].devices:
                    info["device"] = pad.chains[0].devices[0].name
                pads.append(info)
            return {"device": device.name, "pads": pads, "total_pads": len(device.drum_pads)}
        except Exception as e:
            self.log_message("Error getting drum pads: " + str(e))
            raise

    def _set_clip_gain(self, track_index, clip_index, gain, aci=None):
        """Audio clip gain, normalized 0-1 (0.4 is about 0 dB)."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            clip.gain = float(gain)
            return {"gain": clip.gain, "gain_display": getattr(clip, "gain_display_string", "")}
        except Exception as e:
            self.log_message("Error setting clip gain: " + str(e))
            raise

    def _set_clip_pitch(self, track_index, clip_index, coarse=None, fine=None, aci=None):
        """Audio clip transpose: coarse in semitones (-48..48), fine in cents (-500..500)."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            if coarse is not None:
                clip.pitch_coarse = int(coarse)
            if fine is not None:
                clip.pitch_fine = int(fine)
            return {"pitch_coarse": clip.pitch_coarse, "pitch_fine": clip.pitch_fine}
        except Exception as e:
            self.log_message("Error setting clip pitch: " + str(e))
            raise

    def _set_clip_warping(self, track_index, clip_index, warping, aci=None):
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            clip.warping = bool(warping)
            return {"warping": clip.warping}
        except Exception as e:
            self.log_message("Error setting clip warping: " + str(e))
            raise

    def _set_clip_warp_mode(self, track_index, clip_index, warp_mode, aci=None):
        """0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 6=Complex Pro (warping must be on)."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            clip.warp_mode = int(warp_mode)
            return {"warp_mode": clip.warp_mode}
        except Exception as e:
            self.log_message("Error setting clip warp mode: " + str(e))
            raise

    # ---- colors (VyK local patch) ----

    def _apply_color(self, obj, color=None, color_index=None):
        """Set obj's color from a palette slot (color_index 0-69) or an RGB value
        ('#RRGGBB' or an int; Live snaps it to the nearest palette color)."""
        if color_index is not None:
            color_index = int(color_index)
            if color_index < 0 or color_index > 69:
                raise ValueError("color_index must be 0-69 (Live's color palette)")
            obj.color_index = color_index
        elif color is not None:
            if isinstance(color, str):
                text = color.strip().lstrip("#")
                if text.lower().startswith("0x"):
                    text = text[2:]
                if len(text) != 6:
                    raise ValueError("color must look like '#RRGGBB'")
                value = int(text, 16)
            else:
                value = int(color)
            obj.color = value
        else:
            raise ValueError("Give color ('#RRGGBB') or color_index (0-69)")
        return {"color_index": obj.color_index, "color": "#%06X" % (int(obj.color) & 0xFFFFFF)}

    def _set_track_color(self, track_index, color=None, color_index=None):
        try:
            track = self._get_track(track_index)
            result = self._apply_color(track, color, color_index)
            result["track_index"] = track_index
            result["name"] = track.name
            return result
        except Exception as e:
            self.log_message("Error setting track color: " + str(e))
            raise

    def _set_clip_color(self, track_index, clip_index, color=None, color_index=None, aci=None):
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            result = self._apply_color(clip, color, color_index)
            result["name"] = clip.name
            return result
        except Exception as e:
            self.log_message("Error setting clip color: " + str(e))
            raise

    def _set_scene_color(self, scene_index, color=None, color_index=None):
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene = self._song.scenes[scene_index]
            result = self._apply_color(scene, color, color_index)
            result["scene_index"] = scene_index
            result["name"] = scene.name
            return result
        except Exception as e:
            self.log_message("Error setting scene color: " + str(e))
            raise

    # ---- VyK additions: locators, grooves, warp markers, racks, browser search, view, MIDI helpers ----

    def _beats_per_bar(self):
        return self._song.signature_numerator * 4.0 / self._song.signature_denominator

    def _locator_info(self, index, cue):
        return {"index": index, "name": cue.name, "time": cue.time,
                "bar": int(cue.time // self._beats_per_bar()) + 1}

    def _sorted_cues(self):
        return sorted(self._song.cue_points, key=lambda c: c.time)

    def _get_locators(self):
        """Arrangement locators (cue points), sorted by time; the index is the position in that order."""
        try:
            cues = self._sorted_cues()
            return {"locators": [self._locator_info(i, c) for i, c in enumerate(cues)],
                    "count": len(cues), "beats_per_bar": self._beats_per_bar()}
        except Exception as e:
            self.log_message("Error getting locators: " + str(e))
            raise

    def _get_cue(self, locator_index):
        cues = self._sorted_cues()
        if locator_index < 0 or locator_index >= len(cues):
            raise IndexError("Locator index out of range (0-{0})".format(len(cues) - 1))
        return cues[locator_index]

    def _toggle_cue_at(self, time):
        """Song.set_or_delete_cue works at the playhead: move the (stopped) playhead to `time` and
        toggle. The playhead stays there, as when adding a locator by hand."""
        if self._song.is_playing:
            raise Exception("Stop playback first: Live adds and removes locators at the playhead")
        self._song.current_song_time = float(time)
        self._song.set_or_delete_cue()

    def _cue_snapshot(self):
        return [(c.time, c.name) for c in self._song.cue_points]

    def _toggle_and_diff(self, time):
        """Toggle at `time`; return (added times, removed (time, name) pairs). set_or_delete_cue
        is a toggle that may snap to the grid, so callers check what really changed."""
        before = self._cue_snapshot()
        self._toggle_cue_at(time)
        after = self._cue_snapshot()
        added = [t for t, _ in after if not any(abs(t - b) < 1e-6 for b, _ in before)]
        removed = [(t, n) for t, n in before if not any(abs(t - a) < 1e-6 for a, _ in after)]
        return added, removed

    def _undo_cue_changes(self, added, removed):
        """Put the locators back the way they were (re-add removed ones with their names)."""
        for t in added:
            self._toggle_cue_at(t)
        for t, n in removed:
            self._toggle_cue_at(t)
            for c in self._song.cue_points:
                if abs(c.time - t) < 1e-6:
                    c.name = n

    def _create_locator(self, time, name=None):
        """Add a locator at `time` (beats) and name it. Reuses a locator already at that time."""
        try:
            time = float(time)
            if time < 0:
                raise ValueError("time must be >= 0 (beats)")
            for cue in self._song.cue_points:
                if abs(cue.time - time) < 1e-6:
                    if name:
                        cue.name = name
                    return {"created": False, "existing": True, "time": cue.time, "name": cue.name}
            added, removed = self._toggle_and_diff(time)
            if removed:
                # Live snapped onto a grid line that already had a locator and toggled it off
                self._undo_cue_changes(added, removed)
                raise Exception("Live snapped beat {0} onto beat {1}, where locator '{2}' already is; "
                                "it was left untouched (rename it, or pick a time on the grid)".format(
                                    time, removed[0][0], removed[0][1]))
            if added:
                t = added[0]
                if abs(t - time) > self._beats_per_bar():
                    # Far from the request: the playhead did not move
                    self._undo_cue_changes(added, [])
                    raise Exception("Live could not add a locator at beat {0} (it landed at beat {1} "
                                    "and was removed)".format(time, t))
                for c in self._song.cue_points:
                    if abs(c.time - t) < 1e-6:
                        if name:
                            c.name = name
                        result = {"created": True, "time": c.time, "name": c.name,
                                  "bar": int(c.time // self._beats_per_bar()) + 1}
                        if abs(t - time) > 1e-6:
                            result["snapped_from"] = time
                        return result

            # Nothing listed yet: Live may only add the cue point on the next tick; name it then
            bpb = self._beats_per_bar()

            def name_later():
                near = [c for c in self._song.cue_points if abs(c.time - time) <= bpb]
                if near and name:
                    min(near, key=lambda c: abs(c.time - time)).name = name
            self.schedule_message(1, name_later)
            return {"created": "unconfirmed", "time": time, "name": name,
                    "warning": "Live had not listed the locator yet; check with get_locators"}
        except Exception as e:
            self.log_message("Error creating locator: " + str(e))
            raise

    def _rename_locator(self, locator_index, name):
        try:
            cue = self._get_cue(locator_index)
            cue.name = name
            return self._locator_info(locator_index, cue)
        except Exception as e:
            self.log_message("Error renaming locator: " + str(e))
            raise

    def _delete_locator(self, locator_index):
        try:
            cue = self._get_cue(locator_index)
            info = self._locator_info(locator_index, cue)
            target = info["time"]
            added, removed = self._toggle_and_diff(target)
            hit = [r for r in removed if abs(r[0] - target) < 1e-6]
            others = [r for r in removed if abs(r[0] - target) >= 1e-6]
            if added or others or not hit:
                self._undo_cue_changes(added, others if hit else removed)
                raise Exception("Live could not delete the locator at beat {0} (Live's API only removes "
                                "locators on the grid); delete it by hand".format(target))
            info["deleted"] = True
            return info
        except Exception as e:
            self.log_message("Error deleting locator: " + str(e))
            raise

    def _jump_to_locator(self, locator_index):
        try:
            cue = self._get_cue(locator_index)
            cue.jump()
            return self._locator_info(locator_index, cue)
        except Exception as e:
            self.log_message("Error jumping to locator: " + str(e))
            raise

    def _groove_info(self, index, groove):
        info = {"index": index, "name": groove.name}
        for attr in ("base", "timing_amount", "random_amount", "velocity_amount", "quantization_amount"):
            info[attr] = getattr(groove, attr, None)
        return info

    def _get_groove_pool(self):
        """Grooves in the set's Groove Pool (drag them in from the browser's Grooves folder first)."""
        try:
            grooves = list(self._song.groove_pool.grooves)
            return {"grooves": [self._groove_info(i, g) for i, g in enumerate(grooves)],
                    "global_amount": getattr(self._song, "groove_amount", None)}
        except Exception as e:
            self.log_message("Error getting groove pool: " + str(e))
            raise

    def _get_groove(self, groove_index):
        grooves = list(self._song.groove_pool.grooves)
        if groove_index < 0 or groove_index >= len(grooves):
            raise IndexError("Groove index out of range ({0} grooves in the pool)".format(len(grooves)))
        return grooves[groove_index]

    def _set_clip_groove(self, track_index, clip_index, groove_index, aci=None):
        """Assign a Groove Pool groove to a clip; groove_index -1 removes it."""
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            if groove_index is None or int(groove_index) < 0:
                clip.groove = None
                return {"clip": clip.name, "groove": None}
            groove = self._get_groove(int(groove_index))
            clip.groove = groove
            return {"clip": clip.name, "groove": groove.name}
        except Exception as e:
            self.log_message("Error setting clip groove: " + str(e))
            raise

    def _set_groove_params(self, groove_index, timing_amount=None, random_amount=None, velocity_amount=None,
                           quantization_amount=None, base=None, global_amount=None):
        """Edit a groove's amounts (0-1; velocity -1 to 1) and/or the set's global groove amount."""
        try:
            result = {}
            if groove_index is not None and int(groove_index) >= 0:
                groove = self._get_groove(int(groove_index))
                for attr, value in (("timing_amount", timing_amount), ("random_amount", random_amount),
                                    ("velocity_amount", velocity_amount),
                                    ("quantization_amount", quantization_amount)):
                    if value is not None:
                        setattr(groove, attr, float(value))
                if base is not None:
                    groove.base = int(base)
                result["groove"] = self._groove_info(int(groove_index), groove)
            if global_amount is not None:
                self._song.groove_amount = float(global_amount)
            result["global_amount"] = getattr(self._song, "groove_amount", None)
            return result
        except Exception as e:
            self.log_message("Error setting groove params: " + str(e))
            raise

    def _warp_marker_list(self, clip):
        return [{"beat_time": m.beat_time, "sample_time": m.sample_time} for m in clip.warp_markers]

    def _get_warp_markers(self, track_index, clip_index, aci=None):
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            return {"clip": clip.name, "warping": clip.warping, "warp_markers": self._warp_marker_list(clip)}
        except Exception as e:
            self.log_message("Error getting warp markers: " + str(e))
            raise

    def _add_warp_marker(self, track_index, clip_index, beat_time, sample_time=None, aci=None):
        """Add a warp marker at beat_time (clip beats); sample_time (seconds in the file) pins
        that moment of the audio to beat_time."""
        try:
            import Live
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            if not clip.warping:
                raise Exception("Turn warping on first (set_clip_warping)")
            beat_time = float(beat_time)
            if sample_time is None:
                # A marker that keeps the audio where it is: the sample time currently at beat_time
                sample_time = clip.beat_to_sample_time(beat_time)
            clip.add_warp_marker(Live.Clip.WarpMarker(sample_time=float(sample_time), beat_time=beat_time))
            return {"clip": clip.name, "warp_markers": self._warp_marker_list(clip)}
        except Exception as e:
            self.log_message("Error adding warp marker: " + str(e))
            raise

    def _move_warp_marker(self, track_index, clip_index, beat_time, beat_time_distance, aci=None):
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            clip.move_warp_marker(float(beat_time), float(beat_time_distance))
            return {"clip": clip.name, "warp_markers": self._warp_marker_list(clip)}
        except Exception as e:
            self.log_message("Error moving warp marker: " + str(e))
            raise

    def _remove_warp_marker(self, track_index, clip_index, beat_time, aci=None):
        try:
            clip = self._session_clip(track_index, clip_index, midi=False, arrangement_clip_index=aci)
            clip.remove_warp_marker(float(beat_time))
            return {"clip": clip.name, "warp_markers": self._warp_marker_list(clip)}
        except Exception as e:
            self.log_message("Error removing warp marker: " + str(e))
            raise

    def _capture_midi(self, destination=0):
        """Capture MIDI: what was played on armed/monitored MIDI tracks recently becomes a clip.
        destination 0 = auto, 1 = Session, 2 = Arrangement."""
        try:
            self._song.capture_midi(int(destination))
            return {"captured": True, "destination": int(destination)}
        except Exception as e:
            self.log_message("Error capturing MIDI: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            self._song.duplicate_scene(scene_index)
            new_scene = self._song.scenes[scene_index + 1]
            return {"new_scene_index": scene_index + 1, "name": new_scene.name,
                    "scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    def _move_device(self, track_index, device_index, new_index, target_track_index=None):
        """Reorder a device in its chain, or move it to another track."""
        try:
            track = self._get_track(track_index)
            devices = list(track.devices)
            if device_index < 0 or device_index >= len(devices):
                raise IndexError("Device index out of range")
            device = devices[device_index]
            target = track if target_track_index is None else self._get_track(target_track_index)
            position = max(0, min(int(new_index), len(target.devices)))
            self._song.move_device(device, target, position)
            return {"device": device.name, "track": target.name,
                    "devices": [d.name for d in target.devices]}
        except Exception as e:
            self.log_message("Error moving device: " + str(e))
            raise

    def _get_rack(self, track_index, device_index):
        track = self._get_track(track_index)
        devices = list(track.devices)
        if device_index < 0 or device_index >= len(devices):
            raise IndexError("Device index out of range")
        device = devices[device_index]
        if not getattr(device, "can_have_chains", False):
            raise Exception("Device '{0}' is not a rack".format(device.name))
        return device

    def _chain_levels(self, chain):
        """Volume and panning of a rack chain (MIDI Effect Rack chains have neither)."""
        try:
            vol = chain.mixer_device.volume
            return {"volume": vol.value, "volume_display": vol.str_for_value(vol.value),
                    "panning": chain.mixer_device.panning.value}
        except Exception:
            return {}

    def _get_rack_chains(self, track_index, device_index):
        """Chains of an Instrument/Audio Effect/Drum Rack with their mixer and devices."""
        try:
            device = self._get_rack(track_index, device_index)
            chains = []
            for i, chain in enumerate(device.chains):
                info = {"index": i, "name": chain.name, "mute": chain.mute, "solo": chain.solo,
                        "devices": [{"index": j, "name": d.name, "class_name": d.class_name}
                                    for j, d in enumerate(chain.devices)]}
                info.update(self._chain_levels(chain))
                chains.append(info)
            params = list(device.parameters)
            macro_count = int(getattr(device, "visible_macro_count", 8) or 0)
            macros = [{"parameter_index": p_i, "name": params[p_i].name, "value": params[p_i].value,
                       "display": params[p_i].str_for_value(params[p_i].value)}
                      for p_i in range(1, min(1 + macro_count, len(params)))]
            return {"device": device.name, "class_name": device.class_name, "chains": chains,
                    "macros": macros}
        except Exception as e:
            self.log_message("Error getting rack chains: " + str(e))
            raise

    def _set_chain_mixer(self, track_index, device_index, chain_index, mute=None, solo=None,
                         volume=None, panning=None):
        """Mute/solo a rack chain, set its volume (0-1, 0.85 = 0 dB) or panning (-1 to 1)."""
        try:
            device = self._get_rack(track_index, device_index)
            chains = list(device.chains)
            if chain_index < 0 or chain_index >= len(chains):
                raise IndexError("Chain index out of range")
            chain = chains[chain_index]
            if (volume is not None or panning is not None) and not self._chain_levels(chain):
                raise Exception("This rack's chains have no volume or panning (MIDI Effect Rack)")
            if mute is not None:
                chain.mute = bool(mute)
            if solo is not None:
                chain.solo = bool(solo)
            if volume is not None:
                vol = chain.mixer_device.volume
                vol.value = vol.min + float(volume) * (vol.max - vol.min)
            if panning is not None:
                chain.mixer_device.panning.value = max(-1.0, min(1.0, float(panning)))
            result = {"chain": chain.name, "mute": chain.mute, "solo": chain.solo}
            result.update(self._chain_levels(chain))
            return result
        except Exception as e:
            self.log_message("Error setting chain mixer: " + str(e))
            raise

    _SEARCH_CATEGORIES = ("sounds", "drums", "instruments", "audio_effects", "midi_effects", "samples",
                          "clips", "grooves", "user_library", "current_project", "packs", "plugins",
                          "max_for_live")

    def _search_browser(self, query, category="all", max_results=30, max_depth=8, max_nodes=20000,
                        time_budget=6.0):
        """Find browser items whose name contains every word of `query` (case-insensitive).
        Breadth-first, so shallow matches come first; bounded by depth, node count and time."""
        try:
            deadline = time.time() + time_budget
            words = [w for w in query.lower().split() if w]
            if not words:
                raise ValueError("Empty query")
            browser = self.application().browser
            roots = []
            names = self._SEARCH_CATEGORIES if category in (None, "", "all") else (category,)
            for name in names:
                if name == "user_folders":
                    continue
                root = getattr(browser, name, None)
                if root is not None and hasattr(root, "children"):
                    roots.append((name, root))
            if category in (None, "", "all", "user_folders"):
                for folder in getattr(browser, "user_folders", []) or []:
                    roots.append(("user_folders/" + folder.name, folder))
            if not roots:
                raise ValueError("Unknown browser category: {0}".format(category))

            results, visited, seen_uris = [], 0, set()
            level = [(path, item) for path, item in roots]
            depth = 0
            truncated = False
            while level and depth <= max_depth and len(results) < max_results:
                next_level = []
                for path, item in level:
                    for child in item.children:
                        visited += 1
                        if visited > max_nodes or (visited % 200 == 0 and time.time() > deadline):
                            truncated = True
                            break
                        child_path = path + "/" + child.name
                        lname = child.name.lower()
                        uri = getattr(child, "uri", None)
                        if all(w in lname for w in words) and uri not in seen_uris:
                            seen_uris.add(uri)
                            results.append({"name": child.name, "path": child_path, "uri": uri,
                                            "is_loadable": getattr(child, "is_loadable", False),
                                            "is_folder": getattr(child, "is_folder", False)})
                            if len(results) >= max_results:
                                break
                        if getattr(child, "is_folder", False) or getattr(child, "is_device", False):
                            next_level.append((child_path, child))
                    if truncated or len(results) >= max_results:
                        break
                if truncated:
                    break
                level = next_level
                depth += 1
            return {"query": query, "results": results, "count": len(results), "nodes_visited": visited,
                    "truncated": truncated or (bool(level) and depth > max_depth)}
        except Exception as e:
            self.log_message("Error searching browser: " + str(e))
            raise

    def _get_view_state(self):
        try:
            view = self._song.view
            app_view = self.application().view
            result = {"focused_view": None, "selected_track": None, "selected_scene": None, "detail_clip": None}
            result["focused_view"] = getattr(app_view, "focused_document_view", None)
            track = view.selected_track
            if track is not None:
                result["selected_track"] = track.name
                tracks = list(self._song.tracks)
                if track in tracks:
                    result["selected_track_index"] = tracks.index(track)
            scene = view.selected_scene
            if scene is not None:
                result["selected_scene"] = scene.name
                scenes = list(self._song.scenes)
                if scene in scenes:
                    result["selected_scene_index"] = scenes.index(scene)
            clip = view.detail_clip
            if clip is not None:
                result["detail_clip"] = clip.name
            return result
        except Exception as e:
            self.log_message("Error getting view state: " + str(e))
            raise

    def _select_track(self, track_index):
        try:
            track = self._get_track(track_index)
            self._song.view.selected_track = track
            return {"selected_track": track.name}
        except Exception as e:
            self.log_message("Error selecting track: " + str(e))
            raise

    def _select_scene(self, scene_index):
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene = self._song.scenes[scene_index]
            self._song.view.selected_scene = scene
            return {"selected_scene": scene.name}
        except Exception as e:
            self.log_message("Error selecting scene: " + str(e))
            raise

    def _select_clip(self, track_index, clip_index, aci=None):
        """Select a clip and show it in Clip View (session slot or arrangement clip)."""
        try:
            track = self._get_track(track_index)
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=aci)
            self._song.view.selected_track = track
            if aci is None:
                self._song.view.highlighted_clip_slot = track.clip_slots[clip_index]
            self._song.view.detail_clip = clip
            try:
                self.application().view.show_view("Detail/Clip")
            except Exception:
                pass
            return {"selected_clip": clip.name, "track": track.name}
        except Exception as e:
            self.log_message("Error selecting clip: " + str(e))
            raise

    _VIEWS = {"session": "Session", "arrangement": "Arranger", "arranger": "Arranger",
              "clip": "Detail/Clip", "devices": "Detail/DeviceChain", "device": "Detail/DeviceChain",
              "browser": "Browser", "detail": "Detail"}

    def _focus_view(self, view_name):
        """Show and focus Session, Arrangement, Clip View, Device View or the Browser."""
        try:
            name = self._VIEWS.get(str(view_name).lower(), view_name)
            app_view = self.application().view
            app_view.show_view(name)
            app_view.focus_view(name)
            return {"focused": name}
        except Exception as e:
            self.log_message("Error focusing view: " + str(e))
            raise

    def _fold_track(self, track_index, fold=True):
        try:
            track = self._get_track(track_index)
            if not getattr(track, "is_foldable", False):
                raise Exception("Track '{0}' is not a group track".format(track.name))
            track.fold_state = 1 if fold else 0
            return {"track": track.name, "folded": bool(track.fold_state)}
        except Exception as e:
            self.log_message("Error folding track: " + str(e))
            raise

    def _note_window(self, clip, from_time, time_span):
        end = max(clip.length, getattr(clip, "loop_end", 0.0), getattr(clip, "end_marker", 0.0))
        if time_span is None or time_span < 0:
            time_span = max(end - from_time, 0.0) + 1.0
        return from_time, time_span

    def _transpose_clip_notes(self, track_index, clip_index, semitones, from_pitch=0, pitch_span=128,
                              from_time=0.0, time_span=-1.0, aci=None):
        """Shift the notes in a pitch/time window by `semitones` (refused if a note would leave 0-127)."""
        try:
            clip = self._session_clip(track_index, clip_index, midi=True, arrangement_clip_index=aci)
            from_time, time_span = self._note_window(clip, from_time, time_span)
            notes = clip.get_notes_extended(int(from_pitch), int(pitch_span), float(from_time), float(time_span))
            out = [n.pitch for n in notes if not 0 <= n.pitch + int(semitones) <= 127]
            if out:
                raise Exception("{0} note(s) would leave the MIDI range 0-127; nothing was changed".format(len(out)))
            for note in notes:
                note.pitch = note.pitch + int(semitones)
            clip.apply_note_modifications(notes)
            return {"clip": clip.name, "notes_transposed": len(notes), "semitones": int(semitones)}
        except Exception as e:
            self.log_message("Error transposing notes: " + str(e))
            raise

    def _humanize_clip(self, track_index, clip_index, timing=0.0, velocity=0, seed=None,
                       from_time=0.0, time_span=-1.0, aci=None):
        """Nudge note starts randomly by up to +/- `timing` beats and velocities by up to +/- `velocity`."""
        try:
            import random
            rng = random.Random(seed)
            clip = self._session_clip(track_index, clip_index, midi=True, arrangement_clip_index=aci)
            from_time, time_span = self._note_window(clip, from_time, time_span)
            notes = clip.get_notes_extended(0, 128, float(from_time), float(time_span))
            timing = abs(float(timing or 0.0))
            velocity = abs(int(velocity or 0))
            for note in notes:
                if timing:
                    note.start_time = max(0.0, note.start_time + rng.uniform(-timing, timing))
                if velocity:
                    note.velocity = max(1, min(127, int(round(note.velocity + rng.uniform(-velocity, velocity)))))
            clip.apply_note_modifications(notes)
            return {"clip": clip.name, "notes_humanized": len(notes), "timing": timing, "velocity": velocity}
        except Exception as e:
            self.log_message("Error humanizing clip: " + str(e))
            raise

    def _set_track_height(self, track_index, steps=0, collapsed=None, all_tracks=False):
        """Arrangement track height. Live has no pixel height in its API: `collapsed` sets
        Track.View.is_collapsed, and `steps` zooms the height with Application.View.zoom_view
        (up = taller), for the selected track only (modifier) or for all tracks."""
        try:
            steps = int(steps or 0)
            app_view = self.application().view
            result = {}
            track = None
            if not all_tracks:
                track = self._get_track(track_index)
                result["track"] = track.name
                if collapsed is not None:
                    track.view.is_collapsed = bool(collapsed)
            if steps:
                app_view.show_view("Arranger")
                if track is not None:
                    # zoom_view with the modifier changes the highlighted track only
                    self._song.view.selected_track = track
                direction = 0 if steps > 0 else 1
                for _ in range(abs(steps)):
                    app_view.zoom_view(direction, "Arranger", track is not None)
                result["steps"] = steps
                result["scope"] = "track" if track is not None else "all_tracks"
            if track is not None:
                result["collapsed"] = bool(track.view.is_collapsed)
            return result
        except Exception as e:
            self.log_message("Error setting track height: " + str(e))
            raise

    def _unarm_all(self):
        try:
            names = []
            for track in self._song.tracks:
                if getattr(track, "can_be_armed", False) and track.arm:
                    track.arm = False
                    names.append(track.name)
            return {"unarmed": names, "count": len(names)}
        except Exception as e:
            self.log_message("Error unarming tracks: " + str(e))
            raise

    def _get_clip_info(self, track_index, clip_index, arrangement_clip_index=None):
        """Everything about one clip: length, loop and markers, mute, and for audio clips
        warping, warp mode, pitch, gain, file. Session slot or arrangement clip."""
        try:
            clip = self._session_clip(track_index, clip_index, arrangement_clip_index=arrangement_clip_index)
            info = {
                "name": clip.name, "length": clip.length, "is_midi_clip": clip.is_midi_clip,
                "is_audio_clip": clip.is_audio_clip, "looping": clip.looping,
                "loop_start": clip.loop_start, "loop_end": clip.loop_end,
                "start_marker": clip.start_marker, "end_marker": clip.end_marker,
                "muted": clip.muted, "is_playing": clip.is_playing, "is_recording": clip.is_recording,
                "color_index": clip.color_index,
            }
            if arrangement_clip_index is not None:
                info["start_time"] = clip.start_time; info["end_time"] = clip.end_time
            else:
                info["launch_mode"] = clip.launch_mode; info["launch_quantization"] = clip.launch_quantization
            if clip.is_audio_clip:
                info.update({"warping": clip.warping, "warp_mode": clip.warp_mode, "pitch_coarse": clip.pitch_coarse,
                             "pitch_fine": clip.pitch_fine, "gain": clip.gain,
                             "gain_display": getattr(clip, "gain_display_string", ""), "file_path": clip.file_path,
                             "sample_length": getattr(clip, "sample_length", None)})
            return info
        except Exception as e:
            self.log_message("Error getting clip info: " + str(e))
            raise

    def _resample_master(self, seconds=None, name="master rec", start_time=0.0):
        """Record the main output to an audio file: an audio track on Resampling, armed alone,
        arrangement playing from start_time with record mode on, until the last arrangement
        clip ends (or `seconds`). Returns the recorded clip's file path. Runs on the socket
        thread like record_arrangement; Live's own state is touched on the main thread."""
        import time as time_module
        holder = {"track": None, "index": None, "muted": []}
        def is_bounce(tr):
            # an earlier resample_master track: playing it back during this take doubles the mix,
            # and its few ms of offset cancels the sub
            try:
                return str(tr.input_routing_type.display_name) == "Resampling"
            except Exception:
                return False
        def do_on_main(fn):
            done = threading.Event(); err = [None]
            def task():
                try:
                    fn()
                except Exception as e:
                    err[0] = e
                done.set()
            self.schedule_message(0, task)
            done.wait(timeout=5.0)
            if err[0]:
                raise err[0]
        try:
            tempo = self._song.tempo
            end_beat = 0.0
            for tr in self._song.tracks:
                if is_bounce(tr) or tr.is_foldable:
                    continue
                for c in tr.arrangement_clips:
                    end_beat = max(end_beat, c.end_time)
            if seconds is None:
                if end_beat <= start_time:
                    raise Exception("nothing in the arrangement to record (pass `seconds` to record anyway)")
                seconds = (end_beat - start_time + 4.0) * 60.0 / tempo
            def make_track():
                if self._song.is_playing:
                    self._song.stop_playing()
                for tr in self._song.tracks:
                    if is_bounce(tr) and not tr.mute:
                        tr.mute = True
                        holder["muted"].append(tr.name)
                self._song.create_audio_track(-1)
                track = self._song.tracks[-1]
                track.name = name
                for rt in track.available_input_routing_types:
                    if str(rt.display_name) == "Resampling":
                        track.input_routing_type = rt
                        break
                else:
                    raise Exception("no Resampling input on the new track")
                holder["track"] = track; holder["index"] = list(self._song.tracks).index(track)
            def route_and_arm():
                track = holder["track"]
                chans = list(track.available_input_routing_channels)
                if chans:
                    track.input_routing_channel = chans[0]
                track.current_monitoring_state = 2          # Off: never feed the main mix back into itself
                for tr in self._song.tracks:                # Live auto-arms new tracks; an armed MIDI track in
                    if tr.can_be_armed and tr.arm:          # record mode records over its clip instead of playing
                        tr.arm = False
                track.arm = True
            # start_playing() plays from the insert marker, not current_song_time, and a seek made
            # while stopped lands a moment later; continue_playing() from here didn't start the
            # transport at all. What works: from bar 1, stop twice (the marker goes to 0), record
            # on, play. Later in the song: play, seek a pre-roll ahead of start_time while playing
            # (lands at once), then punch record on before the playhead reaches start_time.
            pre_roll = 0.0 if start_time <= 0 else min(8.0, float(start_time))
            rec_from = float(start_time) - pre_roll
            pos = {"v": -1.0, "playing": False}
            def read_pos():
                pos["v"] = float(self._song.current_song_time); pos["playing"] = bool(self._song.is_playing)
            def arrangement():
                self._song.stop_all_clips()
                self._song.back_to_arranger = False        # the arrangement plays (True = session overrides it)
            def stop():
                self._song.stop_playing()
            def play():
                self._song.start_playing()
            def seek():
                self._song.current_song_time = rec_from
            def record_on():
                self._song.record_mode = 1
            def wait_for(ok, what):
                for _ in range(30):
                    do_on_main(read_pos)
                    if ok():
                        return
                    time_module.sleep(0.1)
                raise Exception("{0} (playhead at beat {1})".format(what, pos["v"]))
            for step in (make_track, route_and_arm, arrangement):
                do_on_main(step)
                time_module.sleep(0.15)
            if start_time <= 0:
                do_on_main(stop); time_module.sleep(0.3)
                do_on_main(stop)                            # a second stop returns to the start
                wait_for(lambda: pos["v"] < 0.01, "could not return the playhead to the start")
                do_on_main(record_on); time_module.sleep(0.15)
                do_on_main(play)
                wait_for(lambda: pos["playing"], "the transport did not start")
            else:
                do_on_main(play)
                wait_for(lambda: pos["playing"], "the transport did not start")
                do_on_main(seek)
                wait_for(lambda: rec_from - 0.01 <= pos["v"] < start_time,
                         "could not move the playhead to beat {0}".format(rec_from))
                do_on_main(record_on)
                do_on_main(read_pos)
                if pos["v"] >= start_time:
                    raise Exception("record came on after beat {0}; try again".format(start_time))
            seconds += pre_roll * 60.0 / tempo
            state = {"playing": True, "pos": 0.0}
            def read_state():
                state["playing"] = bool(self._song.is_playing); state["pos"] = float(self._song.current_song_time)
            t0 = time_module.monotonic(); stopped_early = False
            time_module.sleep(1.0)                          # let the transport start before watching it
            while time_module.monotonic() - t0 < seconds:
                time_module.sleep(0.5)
                do_on_main(read_state)                      # LOM reads are only reliable on the main thread
                if not state["playing"]:
                    stopped_early = True
                    break
            out = {}
            def finish():
                self._song.stop_playing()
                self._song.record_mode = 0
                holder["track"].arm = False
                holder["track"].mute = True                 # left playing, the take doubles the mix
                self._song.current_song_time = float(start_time)
            def read_clip():
                clips = list(holder["track"].arrangement_clips)
                rec = clips[-1] if clips else None
                out["file_path"] = rec.file_path if rec else None
                out["length_beats"] = rec.length if rec else 0.0
            do_on_main(finish)
            for _ in range(12):                              # the recorded clip appears a moment after stop
                time_module.sleep(0.5)
                do_on_main(read_clip)
                if out.get("file_path"):
                    break
            return {"track_index": holder["index"], "track_name": name,
                    "file_path": out.get("file_path"), "length_beats": out.get("length_beats", 0.0),
                    "seconds": round(seconds, 1), "recorded_from_beat": rec_from, "pre_roll_beats": pre_roll,
                    "stopped_at_beat": state["pos"], "stopped_early": stopped_early,
                    "muted_earlier_bounces": holder["muted"],
                    "note": "the transport stopped before the end (audio device change or a manual stop?)" if stopped_early else ""}
        except Exception as e:
            self.log_message("Error resampling master: " + str(e))
            raise

    def _get_device_type(self, device):
        """Get the type of a device"""
        try:
            # Simple heuristic - in a real implementation you'd look at the device class
            if device.can_have_drum_pads:
                return "drum_machine"
            elif device.can_have_chains:
                return "rack"
            elif "instrument" in device.class_display_name.lower():
                return "instrument"
            elif "audio_effect" in device.class_name.lower():
                return "audio_effect"
            elif "midi_effect" in device.class_name.lower():
                return "midi_effect"
            else:
                return "unknown"
        except:
            return "unknown"
    
    def get_browser_tree(self, category_type="all"):
        """
        Get a simplified tree of browser categories.
        
        Args:
            category_type: Type of categories to get ('all', 'instruments', 'sounds', etc.)
            
        Returns:
            Dictionary with the browser tree structure
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
            
            result = {
                "type": category_type,
                "categories": [],
                "available_categories": browser_attrs
            }
            
            # Helper function to process a browser item and its children
            def process_item(item, depth=0):
                if not item:
                    return None
                
                result = {
                    "name": item.name if hasattr(item, 'name') else "Unknown",
                    "is_folder": hasattr(item, 'children') and bool(item.children),
                    "is_device": hasattr(item, 'is_device') and item.is_device,
                    "is_loadable": hasattr(item, 'is_loadable') and item.is_loadable,
                    "uri": item.uri if hasattr(item, 'uri') else None,
                    "children": []
                }
                
                
                return result
            
            # Process based on category type and available attributes
            if (category_type == "all" or category_type == "instruments") and hasattr(app.browser, 'instruments'):
                try:
                    instruments = process_item(app.browser.instruments)
                    if instruments:
                        instruments["name"] = "Instruments"  # Ensure consistent naming
                        result["categories"].append(instruments)
                except Exception as e:
                    self.log_message("Error processing instruments: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "sounds") and hasattr(app.browser, 'sounds'):
                try:
                    sounds = process_item(app.browser.sounds)
                    if sounds:
                        sounds["name"] = "Sounds"  # Ensure consistent naming
                        result["categories"].append(sounds)
                except Exception as e:
                    self.log_message("Error processing sounds: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "drums") and hasattr(app.browser, 'drums'):
                try:
                    drums = process_item(app.browser.drums)
                    if drums:
                        drums["name"] = "Drums"  # Ensure consistent naming
                        result["categories"].append(drums)
                except Exception as e:
                    self.log_message("Error processing drums: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "audio_effects") and hasattr(app.browser, 'audio_effects'):
                try:
                    audio_effects = process_item(app.browser.audio_effects)
                    if audio_effects:
                        audio_effects["name"] = "Audio Effects"  # Ensure consistent naming
                        result["categories"].append(audio_effects)
                except Exception as e:
                    self.log_message("Error processing audio_effects: {0}".format(str(e)))
            
            if (category_type == "all" or category_type == "midi_effects") and hasattr(app.browser, 'midi_effects'):
                try:
                    midi_effects = process_item(app.browser.midi_effects)
                    if midi_effects:
                        midi_effects["name"] = "MIDI Effects"
                        result["categories"].append(midi_effects)
                except Exception as e:
                    self.log_message("Error processing midi_effects: {0}".format(str(e)))
            
            # Try to process other potentially available categories
            for attr in browser_attrs:
                if attr not in ['instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects'] and \
                   (category_type == "all" or category_type == attr):
                    try:
                        item = getattr(app.browser, attr)
                        if hasattr(item, 'children') or hasattr(item, 'name'):
                            category = process_item(item)
                            if category:
                                category["name"] = attr.capitalize()
                                result["categories"].append(category)
                    except Exception as e:
                        self.log_message("Error processing {0}: {1}".format(attr, str(e)))
            
            self.log_message("Browser tree generated for {0} with {1} root categories".format(
                category_type, len(result['categories'])))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser tree: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
    
    def get_browser_items_at_path(self, path):
        """
        Get browser items at a specific path.
        
        Args:
            path: Path in the format "category/folder/subfolder"
                 where category is one of: instruments, sounds, drums, audio_effects, midi_effects
                 or any other available browser category
                 
        Returns:
            Dictionary with items at the specified path
        """
        try:
            # Access the application's browser instance instead of creating a new one
            app = self.application()
            if not app:
                raise RuntimeError("Could not access Live application")
                
            # Check if browser is available
            if not hasattr(app, 'browser') or app.browser is None:
                raise RuntimeError("Browser is not available in the Live application")
            
            # Log available browser attributes to help diagnose issues
            browser_attrs = [attr for attr in dir(app.browser) if not attr.startswith('_')]
            self.log_message("Available browser attributes: {0}".format(browser_attrs))
                
            # Parse the path
            path_parts = path.split("/")
            if not path_parts:
                raise ValueError("Invalid path")
            
            # Determine the root category
            root_category = path_parts[0].lower()
            current_item = None
            
            # Check standard categories first
            if root_category == "instruments" and hasattr(app.browser, 'instruments'):
                current_item = app.browser.instruments
            elif root_category == "sounds" and hasattr(app.browser, 'sounds'):
                current_item = app.browser.sounds
            elif root_category == "drums" and hasattr(app.browser, 'drums'):
                current_item = app.browser.drums
            elif root_category == "audio_effects" and hasattr(app.browser, 'audio_effects'):
                current_item = app.browser.audio_effects
            elif root_category == "midi_effects" and hasattr(app.browser, 'midi_effects'):
                current_item = app.browser.midi_effects
            else:
                # Try to find the category in other browser attributes
                found = False
                for attr in browser_attrs:
                    if attr.lower() == root_category:
                        try:
                            current_item = getattr(app.browser, attr)
                            found = True
                            break
                        except Exception as e:
                            self.log_message("Error accessing browser attribute {0}: {1}".format(attr, str(e)))
                
                if not found:
                    # If we still haven't found the category, return available categories
                    return {
                        "path": path,
                        "error": "Unknown or unavailable category: {0}".format(root_category),
                        "available_categories": browser_attrs,
                        "items": []
                    }
            
            # Navigate through the path
            for i in range(1, len(path_parts)):
                part = path_parts[i]
                if not part:  # Skip empty parts
                    continue
                
                if not hasattr(current_item, 'children'):
                    return {
                        "path": path,
                        "error": "Item at '{0}' has no children".format('/'.join(path_parts[:i])),
                        "items": []
                    }
                
                found = False
                for child in current_item.children:
                    if hasattr(child, 'name') and child.name.lower() == part.lower():
                        current_item = child
                        found = True
                        break
                
                if not found:
                    return {
                        "path": path,
                        "error": "Path part '{0}' not found".format(part),
                        "items": []
                    }
            
            # Get items at the current path
            items = []
            if hasattr(current_item, 'children'):
                for child in current_item.children:
                    item_info = {
                        "name": child.name if hasattr(child, 'name') else "Unknown",
                        "is_folder": hasattr(child, 'children') and bool(child.children),
                        "is_device": hasattr(child, 'is_device') and child.is_device,
                        "is_loadable": hasattr(child, 'is_loadable') and child.is_loadable,
                        "uri": child.uri if hasattr(child, 'uri') else None
                    }
                    items.append(item_info)
            
            result = {
                "path": path,
                "name": current_item.name if hasattr(current_item, 'name') else "Unknown",
                "uri": current_item.uri if hasattr(current_item, 'uri') else None,
                "is_folder": hasattr(current_item, 'children') and bool(current_item.children),
                "is_device": hasattr(current_item, 'is_device') and current_item.is_device,
                "is_loadable": hasattr(current_item, 'is_loadable') and current_item.is_loadable,
                "items": items
            }
            
            self.log_message("Retrieved {0} items at path: {1}".format(len(items), path))
            return result
            
        except Exception as e:
            self.log_message("Error getting browser items at path: {0}".format(str(e)))
            self.log_message(traceback.format_exc())
            raise
