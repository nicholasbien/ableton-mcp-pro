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
        
        # Start the socket server
        self.start_server()
        
        self.log_message("AbletonMCP initialized")
        
        # Show a message in Ableton
        self.show_message("AbletonMCP: Listening for commands on port " + str(DEFAULT_PORT))
    
    def disconnect(self):
        """Called when Ableton closes or the control surface is removed"""
        self.log_message("AbletonMCP disconnecting...")
        self.running = False
        
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
            # Route the command to the appropriate handler
            if command_type == "get_session_info":
                response["result"] = self._get_session_info()
            elif command_type == "get_track_info":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_info(track_index)
            # Commands that modify Live's state should be scheduled on the main thread
            elif command_type == "get_device_parameters":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_device_parameters(track_index, device_index)
            elif command_type == "get_arrangement_info":
                response["result"] = self._get_arrangement_info()
            elif command_type == "get_arrangement_clips":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_arrangement_clips(track_index)
            elif command_type == "get_full_arrangement":
                response["result"] = self._get_full_arrangement()
            elif command_type == "get_clip_notes":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                response["result"] = self._get_clip_notes(track_index, clip_index)
            elif command_type == "get_clip_envelope":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                device_index = params.get("device_index", 0)
                parameter_index = params.get("parameter_index", 0)
                response["result"] = self._get_clip_envelope(track_index, clip_index, device_index, parameter_index)
            elif command_type == "get_clip_info":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                response["result"] = self._get_clip_info(track_index, clip_index)
            elif command_type == "get_warp_markers":
                track_index = params.get("track_index", 0)
                clip_index = params.get("clip_index", 0)
                response["result"] = self._get_warp_markers(track_index, clip_index)
            elif command_type == "get_track_routing":
                track_index = params.get("track_index", 0)
                response["result"] = self._get_track_routing(track_index)
            elif command_type == "get_cue_points":
                response["result"] = self._get_cue_points()
            elif command_type == "get_scene_info":
                scene_index = params.get("scene_index", 0)
                response["result"] = self._get_scene_info(scene_index)
            elif command_type == "get_drum_pads":
                track_index = params.get("track_index", 0)
                device_index = params.get("device_index", 0)
                response["result"] = self._get_drum_pads(track_index, device_index)
            elif command_type == "record_arrangement":
                # Runs on socket thread with schedule_message for main thread ops
                sections = params.get("sections", [])
                response["result"] = self._record_arrangement(sections)
            elif command_type in ["create_midi_track", "set_track_name",
                                 "create_clip", "create_audio_clip", "add_notes_to_clip", "set_clip_name",
                                 "set_tempo", "fire_clip", "stop_clip",
                                 "start_playback", "stop_playback", "play_arrangement",
                                 "load_browser_item",
                                 "load_instrument_or_effect",
                                 "set_device_parameter", "batch_set_device_parameters",
                                 "set_track_volume", "set_track_panning",
                                 "fire_scene", "set_song_time", "set_record_mode",
                                 "set_arrangement_overdub", "set_back_to_arranger",
                                 "set_arrangement_loop",
                                 "set_track_mute", "set_track_solo",
                                 "delete_clip", "duplicate_clip",
                                 "create_scene", "delete_scene", "set_scene_name",
                                 "create_audio_track", "delete_track",
                                 "delete_device", "duplicate_track", "set_clip_loop",
                                 "set_track_arm", "set_send_level", "set_time_signature",
                                 "set_metronome", "set_clip_envelope", "clear_clip_envelope",
                                 "undo", "redo",
                                 "remove_notes", "quantize_clip", "duplicate_clip_loop",
                                 "duplicate_region", "crop_clip",
                                 "set_clip_color", "set_clip_muted", "set_clip_launch_mode",
                                 "set_clip_launch_quantization", "set_clip_legato",
                                 "set_clip_start_marker", "set_clip_end_marker", "set_clip_ram_mode",
                                 "set_clip_warping", "set_clip_warp_mode", "set_clip_gain",
                                 "set_clip_pitch", "add_warp_marker", "move_warp_marker",
                                 "delete_warp_marker",
                                 "capture_midi", "capture_and_insert_scene", "stop_all_clips",
                                 "tap_tempo", "jump_by", "set_or_delete_cue",
                                 "jump_to_next_cue", "jump_to_prev_cue",
                                 "set_swing_amount", "set_groove_amount", "continue_playing",
                                 "set_session_record", "set_session_automation_record",
                                 "re_enable_automation", "set_punch_in", "set_punch_out",
                                 "set_exclusive_arm",
                                 "create_return_track", "delete_return_track",
                                 "set_track_color", "set_track_monitoring",
                                 "set_track_input_routing", "set_track_output_routing",
                                 "fold_track",
                                 "set_scene_color", "duplicate_scene",
                                 "set_crossfader", "set_crossfade_assign", "set_cue_volume",
                                 "set_device_enabled",
                                 "set_scale", "set_scene_tempo"]:
                # Use a thread-safe approach with a response queue
                response_queue = queue.Queue()
                
                # Define a function to execute on the main thread
                def main_thread_task():
                    try:
                        result = None
                        if command_type == "create_midi_track":
                            index = params.get("index", -1)
                            result = self._create_midi_track(index)
                        elif command_type == "set_track_name":
                            track_index = params.get("track_index", 0)
                            name = params.get("name", "")
                            result = self._set_track_name(track_index, name)
                        elif command_type == "create_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            length = params.get("length", 4.0)
                            result = self._create_clip(track_index, clip_index, length)
                        elif command_type == "create_audio_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            file_path = params.get("file_path", "")
                            result = self._create_audio_clip(track_index, clip_index, file_path)
                        elif command_type == "add_notes_to_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            notes = params.get("notes", [])
                            result = self._add_notes_to_clip(track_index, clip_index, notes)
                        elif command_type == "set_clip_name":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            name = params.get("name", "")
                            result = self._set_clip_name(track_index, clip_index, name)
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
                            result = self._set_back_to_arranger()
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
                        # ============ NEW COMMAND ROUTING ============
                        elif command_type == "remove_notes":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            from_pitch = params.get("from_pitch", 0)
                            pitch_span = params.get("pitch_span", 128)
                            from_time = params.get("from_time", 0)
                            time_span = params.get("time_span", 4.0)
                            result = self._remove_notes(track_index, clip_index, from_pitch, pitch_span, from_time, time_span)
                        elif command_type == "quantize_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            grid = params.get("grid", 4)
                            strength = params.get("strength", 1.0)
                            result = self._quantize_clip(track_index, clip_index, grid, strength)
                        elif command_type == "duplicate_clip_loop":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._duplicate_clip_loop(track_index, clip_index)
                        elif command_type == "duplicate_region":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            region_start = params.get("region_start", 0.0)
                            region_length = params.get("region_length", 4.0)
                            destination_time = params.get("destination_time", 4.0)
                            pitch = params.get("pitch", -1)
                            transposition_amount = params.get("transposition_amount", 0)
                            result = self._duplicate_region(track_index, clip_index, region_start, region_length, destination_time, pitch, transposition_amount)
                        elif command_type == "crop_clip":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            result = self._crop_clip(track_index, clip_index)
                        elif command_type == "set_clip_color":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            color_index = params.get("color_index", 0)
                            result = self._set_clip_color(track_index, clip_index, color_index)
                        elif command_type == "set_clip_muted":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            muted = params.get("muted", False)
                            result = self._set_clip_muted(track_index, clip_index, muted)
                        elif command_type == "set_clip_launch_mode":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            launch_mode = params.get("launch_mode", 0)
                            result = self._set_clip_launch_mode(track_index, clip_index, launch_mode)
                        elif command_type == "set_clip_launch_quantization":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            quantization = params.get("quantization", 0)
                            result = self._set_clip_launch_quantization(track_index, clip_index, quantization)
                        elif command_type == "set_clip_legato":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            legato = params.get("legato", False)
                            result = self._set_clip_legato(track_index, clip_index, legato)
                        elif command_type == "set_clip_start_marker":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            position = params.get("position", 0.0)
                            result = self._set_clip_start_marker(track_index, clip_index, position)
                        elif command_type == "set_clip_end_marker":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            position = params.get("position", 0.0)
                            result = self._set_clip_end_marker(track_index, clip_index, position)
                        elif command_type == "set_clip_ram_mode":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            ram_mode = params.get("ram_mode", False)
                            result = self._set_clip_ram_mode(track_index, clip_index, ram_mode)
                        elif command_type == "set_clip_warping":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            warping = params.get("warping", True)
                            result = self._set_clip_warping(track_index, clip_index, warping)
                        elif command_type == "set_clip_warp_mode":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            warp_mode = params.get("warp_mode", 0)
                            result = self._set_clip_warp_mode(track_index, clip_index, warp_mode)
                        elif command_type == "set_clip_gain":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            gain = params.get("gain", 0.0)
                            result = self._set_clip_gain(track_index, clip_index, gain)
                        elif command_type == "set_clip_pitch":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            coarse = params.get("coarse", None)
                            fine = params.get("fine", None)
                            result = self._set_clip_pitch(track_index, clip_index, coarse, fine)
                        elif command_type == "add_warp_marker":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            beat_time = params.get("beat_time", 0.0)
                            sample_time = params.get("sample_time", 0.0)
                            result = self._add_warp_marker(track_index, clip_index, beat_time, sample_time)
                        elif command_type == "move_warp_marker":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            beat_time = params.get("beat_time", 0.0)
                            new_sample_time = params.get("new_sample_time", 0.0)
                            result = self._move_warp_marker(track_index, clip_index, beat_time, new_sample_time)
                        elif command_type == "delete_warp_marker":
                            track_index = params.get("track_index", 0)
                            clip_index = params.get("clip_index", 0)
                            beat_time = params.get("beat_time", 0.0)
                            result = self._delete_warp_marker(track_index, clip_index, beat_time)
                        elif command_type == "capture_midi":
                            result = self._capture_midi()
                        elif command_type == "capture_and_insert_scene":
                            result = self._capture_and_insert_scene()
                        elif command_type == "stop_all_clips":
                            quantized = params.get("quantized", True)
                            result = self._stop_all_clips(quantized)
                        elif command_type == "tap_tempo":
                            result = self._tap_tempo()
                        elif command_type == "jump_by":
                            amount = params.get("amount", 0.0)
                            result = self._jump_by(amount)
                        elif command_type == "set_or_delete_cue":
                            result = self._set_or_delete_cue()
                        elif command_type == "jump_to_next_cue":
                            result = self._jump_to_next_cue()
                        elif command_type == "jump_to_prev_cue":
                            result = self._jump_to_prev_cue()
                        elif command_type == "set_swing_amount":
                            amount = params.get("amount", 0.0)
                            result = self._set_swing_amount(amount)
                        elif command_type == "set_groove_amount":
                            amount = params.get("amount", 0.0)
                            result = self._set_groove_amount(amount)
                        elif command_type == "continue_playing":
                            result = self._continue_playing()
                        elif command_type == "set_session_record":
                            on = params.get("on", False)
                            result = self._set_session_record(on)
                        elif command_type == "set_session_automation_record":
                            on = params.get("on", False)
                            result = self._set_session_automation_record(on)
                        elif command_type == "re_enable_automation":
                            result = self._re_enable_automation()
                        elif command_type == "set_punch_in":
                            on = params.get("on", False)
                            result = self._set_punch_in(on)
                        elif command_type == "set_punch_out":
                            on = params.get("on", False)
                            result = self._set_punch_out(on)
                        elif command_type == "set_exclusive_arm":
                            on = params.get("on", False)
                            result = self._set_exclusive_arm(on)
                        elif command_type == "create_return_track":
                            result = self._create_return_track()
                        elif command_type == "delete_return_track":
                            index = params.get("index", 0)
                            result = self._delete_return_track(index)
                        elif command_type == "set_track_color":
                            track_index = params.get("track_index", 0)
                            color_index = params.get("color_index", 0)
                            result = self._set_track_color(track_index, color_index)
                        elif command_type == "set_track_monitoring":
                            track_index = params.get("track_index", 0)
                            state = params.get("state", 1)
                            result = self._set_track_monitoring(track_index, state)
                        elif command_type == "set_track_input_routing":
                            track_index = params.get("track_index", 0)
                            routing_type_name = params.get("routing_type_name", "")
                            result = self._set_track_input_routing(track_index, routing_type_name)
                        elif command_type == "set_track_output_routing":
                            track_index = params.get("track_index", 0)
                            routing_type_name = params.get("routing_type_name", "")
                            result = self._set_track_output_routing(track_index, routing_type_name)
                        elif command_type == "fold_track":
                            track_index = params.get("track_index", 0)
                            fold = params.get("fold", True)
                            result = self._fold_track(track_index, fold)
                        elif command_type == "set_scene_color":
                            scene_index = params.get("scene_index", 0)
                            color_index = params.get("color_index", 0)
                            result = self._set_scene_color(scene_index, color_index)
                        elif command_type == "duplicate_scene":
                            scene_index = params.get("scene_index", 0)
                            result = self._duplicate_scene(scene_index)
                        elif command_type == "set_crossfader":
                            position = params.get("position", 0.5)
                            result = self._set_crossfader(position)
                        elif command_type == "set_crossfade_assign":
                            track_index = params.get("track_index", 0)
                            assign = params.get("assign", 0)
                            result = self._set_crossfade_assign(track_index, assign)
                        elif command_type == "set_cue_volume":
                            volume = params.get("volume", 0.85)
                            result = self._set_cue_volume(volume)
                        elif command_type == "set_device_enabled":
                            track_index = params.get("track_index", 0)
                            device_index = params.get("device_index", 0)
                            enabled = params.get("enabled", True)
                            result = self._set_device_enabled(track_index, device_index, enabled)
                        elif command_type == "set_scale":
                            name = params.get("name", None)
                            root_note = params.get("root_note", None)
                            result = self._set_scale(name, root_note)
                        elif command_type == "set_scene_tempo":
                            scene_index = params.get("scene_index", 0)
                            tempo = params.get("tempo", 120.0)
                            result = self._set_scene_tempo(scene_index, tempo)

                        # Put the result in the queue
                        response_queue.put({"status": "success", "result": result})
                    except Exception as e:
                        self.log_message("Error in main thread task: " + str(e))
                        self.log_message(traceback.format_exc())
                        response_queue.put({"status": "error", "message": str(e)})
                
                # Schedule the task to run on the main thread
                try:
                    self.schedule_message(0, main_thread_task)
                except AssertionError:
                    # If we're already on the main thread, execute directly
                    main_thread_task()
                
                # Wait for the response with a timeout
                try:
                    cmd_timeout = 300.0 if command_type == "record_arrangement" else 10.0
                    task_response = response_queue.get(timeout=cmd_timeout)
                    if task_response.get("status") == "error":
                        response["status"] = "error"
                        response["message"] = task_response.get("message", "Unknown error")
                    else:
                        response["result"] = task_response.get("result", {})
                except queue.Empty:
                    response["status"] = "error"
                    response["message"] = "Timeout waiting for operation to complete"
            elif command_type == "get_browser_item":
                uri = params.get("uri", None)
                path = params.get("path", None)
                response["result"] = self._get_browser_item(uri, path)
            elif command_type == "get_browser_categories":
                category_type = params.get("category_type", "all")
                response["result"] = self._get_browser_categories(category_type)
            elif command_type == "get_browser_items":
                path = params.get("path", "")
                item_type = params.get("item_type", "all")
                response["result"] = self._get_browser_items(path, item_type)
            # Add the new browser commands
            elif command_type == "get_browser_tree":
                category_type = params.get("category_type", "all")
                response["result"] = self.get_browser_tree(category_type)
            elif command_type == "get_browser_items_at_path":
                path = params.get("path", "")
                response["result"] = self.get_browser_items_at_path(path)
            else:
                response["status"] = "error"
                response["message"] = "Unknown command: " + command_type
        except Exception as e:
            self.log_message("Error processing command: " + str(e))
            self.log_message(traceback.format_exc())
            response["status"] = "error"
            response["message"] = str(e)
        
        return response
    
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
                "master_track": {
                    "name": "Master",
                    "volume": self._song.master_track.mixer_device.volume.value,
                    "panning": self._song.master_track.mixer_device.panning.value
                }
            }
            return result
        except Exception as e:
            self.log_message("Error getting session info: " + str(e))
            raise
    
    def _get_track_info(self, track_index):
        """Get information about a track"""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")
            
            track = self._song.tracks[track_index]
            
            # Get clip slots
            clip_slots = []
            for slot_index, slot in enumerate(track.clip_slots):
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
            
            result = {
                "index": track_index,
                "name": track.name,
                "is_audio_track": track.has_audio_input,
                "is_midi_track": track.has_midi_input,
                "mute": track.mute,
                "solo": track.solo,
                "arm": track.arm,
                "volume": track.mixer_device.volume.value,
                "panning": track.mixer_device.panning.value,
                "clip_slots": clip_slots,
                "devices": devices
            }
            return result
        except Exception as e:
            self.log_message("Error getting track info: " + str(e))
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

    def _set_back_to_arranger(self):
        """Return to arrangement view from session"""
        try:
            self._song.back_to_arranger = True
            return {
                "back_to_arranger": True
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
                    clip_info = {
                        "name": clip.name,
                        "start_time": clip.start_time if hasattr(clip, 'start_time') else 0,
                        "end_time": clip.end_time if hasattr(clip, 'end_time') else 0,
                        "length": clip.length,
                        "is_midi_clip": clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else False,
                        "is_audio_clip": clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False,
                    }
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
                if hasattr(track, 'arrangement_clips'):
                    for clip in track.arrangement_clips:
                        clips.append({
                            "name": clip.name,
                            "start_time": clip.start_time if hasattr(clip, 'start_time') else 0,
                            "end_time": clip.end_time if hasattr(clip, 'end_time') else 0,
                            "length": clip.length,
                            "is_midi_clip": clip.is_midi_clip if hasattr(clip, 'is_midi_clip') else False,
                        })
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

    def _record_arrangement(self, sections):
        """Record session clips into arrangement by firing scenes at timed intervals.
        sections: list of {"scene_index": int, "bars": int}

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

                # Seek to start
                def seek_start():
                    self._song.current_song_time = 0.0
                    for _ in range(5):
                        if abs(self._song.current_song_time) < 0.5:
                            break
                        self._song.current_song_time = 0.0
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

                    target_beat = (total_bars + bars) * beats_per_bar
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

    # ============ NEW COMMANDS ============

    def _get_clip_info(self, track_index, clip_index):
        """Get detailed info about a specific clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            result = {
                "name": clip.name,
                "color": clip.color,
                "color_index": clip.color_index,
                "length": clip.length,
                "is_midi_clip": clip.is_midi_clip,
                "is_audio_clip": clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False,
                "looping": clip.looping,
                "loop_start": clip.loop_start,
                "loop_end": clip.loop_end,
                "start_marker": clip.start_marker,
                "end_marker": clip.end_marker if hasattr(clip, 'end_marker') else 0,
                "muted": clip.muted,
                "position": clip.position,
                "is_playing": clip.is_playing,
                "is_recording": clip.is_recording,
                "launch_mode": clip.launch_mode,
                "launch_quantization": clip.launch_quantization if hasattr(clip, 'launch_quantization') else 0,
                "legato": clip.legato if hasattr(clip, 'legato') else False,
                "ram_mode": clip.ram_mode if hasattr(clip, 'ram_mode') else False,
            }
            # Audio-specific properties
            if clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False:
                result["warping"] = clip.warping if hasattr(clip, 'warping') else False
                result["warp_mode"] = clip.warp_mode if hasattr(clip, 'warp_mode') else 0
                result["pitch_coarse"] = clip.pitch_coarse if hasattr(clip, 'pitch_coarse') else 0
                result["pitch_fine"] = clip.pitch_fine if hasattr(clip, 'pitch_fine') else 0
                result["gain"] = clip.gain if hasattr(clip, 'gain') else 0
                result["file_path"] = clip.file_path if hasattr(clip, 'file_path') else ""
            return result
        except Exception as e:
            self.log_message("Error getting clip info: " + str(e))
            raise

    def _remove_notes(self, track_index, clip_index, from_pitch, pitch_span, from_time, time_span):
        """Remove notes from a MIDI clip within the specified range"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not clip.is_midi_clip:
                raise Exception("Not a MIDI clip")
            clip.remove_notes_extended(from_pitch=from_pitch, pitch_span=pitch_span, from_time=from_time, time_span=time_span)
            return {"removed": True}
        except Exception as e:
            self.log_message("Error removing notes: " + str(e))
            raise

    def _quantize_clip(self, track_index, clip_index, grid, strength):
        """Quantize notes in a clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.quantize(grid, strength)
            return {"quantized": True, "grid": grid, "strength": strength}
        except Exception as e:
            self.log_message("Error quantizing clip: " + str(e))
            raise

    def _duplicate_clip_loop(self, track_index, clip_index):
        """Double the loop length and duplicate contents"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.duplicate_loop()
            return {"new_length": clip.length, "loop_end": clip.loop_end}
        except Exception as e:
            self.log_message("Error duplicating clip loop: " + str(e))
            raise

    def _duplicate_region(self, track_index, clip_index, region_start, region_length, destination_time, pitch=-1, transposition_amount=0):
        """Duplicate a region within a MIDI clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not clip.is_midi_clip:
                raise Exception("Not a MIDI clip")
            clip.duplicate_region(region_start, region_length, destination_time, pitch, transposition_amount)
            return {"duplicated": True}
        except Exception as e:
            self.log_message("Error duplicating region: " + str(e))
            raise

    def _crop_clip(self, track_index, clip_index):
        """Crop clip to loop boundaries"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.crop()
            return {"cropped": True, "length": clip.length}
        except Exception as e:
            self.log_message("Error cropping clip: " + str(e))
            raise

    def _set_clip_color(self, track_index, clip_index, color_index):
        """Set clip color by color index"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.color_index = color_index
            return {"color_index": clip.color_index}
        except Exception as e:
            self.log_message("Error setting clip color: " + str(e))
            raise

    def _set_clip_muted(self, track_index, clip_index, muted):
        """Mute or unmute a clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.muted = muted
            return {"muted": clip.muted}
        except Exception as e:
            self.log_message("Error setting clip muted: " + str(e))
            raise

    def _set_clip_launch_mode(self, track_index, clip_index, launch_mode):
        """Set clip launch mode (0=Trigger, 1=Gate, 2=Toggle, 3=Repeat)"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.launch_mode = launch_mode
            return {"launch_mode": clip.launch_mode}
        except Exception as e:
            self.log_message("Error setting clip launch mode: " + str(e))
            raise

    def _set_clip_launch_quantization(self, track_index, clip_index, quantization):
        """Set per-clip launch quantization"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.launch_quantization = quantization
            return {"launch_quantization": clip.launch_quantization}
        except Exception as e:
            self.log_message("Error setting clip launch quantization: " + str(e))
            raise

    def _set_clip_legato(self, track_index, clip_index, legato):
        """Enable or disable legato on a clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.legato = legato
            return {"legato": clip.legato}
        except Exception as e:
            self.log_message("Error setting clip legato: " + str(e))
            raise

    def _set_clip_start_marker(self, track_index, clip_index, position):
        """Set clip start marker position"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.start_marker = position
            return {"start_marker": clip.start_marker}
        except Exception as e:
            self.log_message("Error setting clip start marker: " + str(e))
            raise

    def _set_clip_end_marker(self, track_index, clip_index, position):
        """Set clip end marker position"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.end_marker = position
            return {"end_marker": clip.end_marker}
        except Exception as e:
            self.log_message("Error setting clip end marker: " + str(e))
            raise

    def _set_clip_ram_mode(self, track_index, clip_index, ram_mode):
        """Set clip RAM mode (True = load into RAM)"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            clip.ram_mode = ram_mode
            return {"ram_mode": clip.ram_mode}
        except Exception as e:
            self.log_message("Error setting clip RAM mode: " + str(e))
            raise

    def _set_clip_warping(self, track_index, clip_index, warping):
        """Enable or disable warping on an audio clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.warping = warping
            return {"warping": clip.warping}
        except Exception as e:
            self.log_message("Error setting clip warping: " + str(e))
            raise

    def _set_clip_warp_mode(self, track_index, clip_index, warp_mode):
        """Set warp mode (0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 6=Complex Pro)"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.warp_mode = warp_mode
            return {"warp_mode": clip.warp_mode}
        except Exception as e:
            self.log_message("Error setting warp mode: " + str(e))
            raise

    def _set_clip_gain(self, track_index, clip_index, gain):
        """Set audio clip gain (0.0 to 1.0 normalized)"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.gain = gain
            return {"gain": clip.gain, "gain_display": clip.gain_display_string if hasattr(clip, 'gain_display_string') else ""}
        except Exception as e:
            self.log_message("Error setting clip gain: " + str(e))
            raise

    def _set_clip_pitch(self, track_index, clip_index, coarse=None, fine=None):
        """Set audio clip pitch (coarse: -48 to 48 semitones, fine: -500 to 500 cents)"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            if coarse is not None:
                clip.pitch_coarse = coarse
            if fine is not None:
                clip.pitch_fine = fine
            return {"pitch_coarse": clip.pitch_coarse, "pitch_fine": clip.pitch_fine}
        except Exception as e:
            self.log_message("Error setting clip pitch: " + str(e))
            raise

    def _add_warp_marker(self, track_index, clip_index, beat_time, sample_time):
        """Add a warp marker to an audio clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.add_warp_marker(beat_time, sample_time)
            return {"added": True, "beat_time": beat_time, "sample_time": sample_time}
        except Exception as e:
            self.log_message("Error adding warp marker: " + str(e))
            raise

    def _move_warp_marker(self, track_index, clip_index, beat_time, new_sample_time):
        """Move a warp marker in an audio clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.move_warp_marker(beat_time, new_sample_time)
            return {"moved": True}
        except Exception as e:
            self.log_message("Error moving warp marker: " + str(e))
            raise

    def _delete_warp_marker(self, track_index, clip_index, beat_time):
        """Delete a warp marker from an audio clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            clip.delete_warp_marker(beat_time)
            return {"deleted": True}
        except Exception as e:
            self.log_message("Error deleting warp marker: " + str(e))
            raise

    def _get_warp_markers(self, track_index, clip_index):
        """Get all warp markers from an audio clip"""
        try:
            track = self._get_track(track_index)
            clip_slot = track.clip_slots[clip_index]
            if not clip_slot.has_clip:
                raise Exception("No clip in slot")
            clip = clip_slot.clip
            if not (clip.is_audio_clip if hasattr(clip, 'is_audio_clip') else False):
                raise Exception("Not an audio clip")
            markers = []
            if hasattr(clip, 'warp_markers'):
                for marker in clip.warp_markers:
                    markers.append({
                        "beat_time": marker.beat_time,
                        "sample_time": marker.sample_time
                    })
            return {
                "markers": markers,
                "sample_length": clip.sample_length if hasattr(clip, 'sample_length') else 0
            }
        except Exception as e:
            self.log_message("Error getting warp markers: " + str(e))
            raise

    def _capture_midi(self):
        """Capture recently played MIDI"""
        try:
            if hasattr(self._song, 'can_capture_midi') and self._song.can_capture_midi:
                self._song.capture_midi()
                return {"captured": True}
            else:
                raise Exception("No MIDI to capture")
        except Exception as e:
            self.log_message("Error capturing MIDI: " + str(e))
            raise

    def _capture_and_insert_scene(self):
        """Capture playing clips and insert as new scene"""
        try:
            self._song.capture_and_insert_scene()
            return {"captured": True, "scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error capturing scene: " + str(e))
            raise

    def _stop_all_clips(self, quantized=True):
        """Stop all playing clips"""
        try:
            self._song.stop_all_clips(quantized)
            return {"stopped": True}
        except Exception as e:
            self.log_message("Error stopping all clips: " + str(e))
            raise

    def _tap_tempo(self):
        """Tap tempo"""
        try:
            self._song.tap_tempo()
            return {"tempo": self._song.tempo}
        except Exception as e:
            self.log_message("Error tapping tempo: " + str(e))
            raise

    def _jump_by(self, amount):
        """Jump playhead by relative amount in beats"""
        try:
            self._song.jump_by(amount)
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping: " + str(e))
            raise

    def _set_or_delete_cue(self):
        """Set or delete cue point at current position"""
        try:
            self._song.set_or_delete_cue()
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error with cue point: " + str(e))
            raise

    def _jump_to_next_cue(self):
        """Jump to next cue point"""
        try:
            self._song.jump_to_next_cue()
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping to next cue: " + str(e))
            raise

    def _jump_to_prev_cue(self):
        """Jump to previous cue point"""
        try:
            self._song.jump_to_prev_cue()
            return {"current_song_time": self._song.current_song_time}
        except Exception as e:
            self.log_message("Error jumping to prev cue: " + str(e))
            raise

    def _set_swing_amount(self, amount):
        """Set global swing amount (0.0 to 1.0)"""
        try:
            self._song.swing_amount = amount
            return {"swing_amount": self._song.swing_amount}
        except Exception as e:
            self.log_message("Error setting swing: " + str(e))
            raise

    def _set_groove_amount(self, amount):
        """Set global groove amount (0.0 to 1.0)"""
        try:
            self._song.groove_amount = amount
            return {"groove_amount": self._song.groove_amount}
        except Exception as e:
            self.log_message("Error setting groove: " + str(e))
            raise

    def _continue_playing(self):
        """Continue playing from current position"""
        try:
            self._song.continue_playing()
            return {"is_playing": self._song.is_playing}
        except Exception as e:
            self.log_message("Error continuing playback: " + str(e))
            raise

    def _set_session_record(self, on):
        """Enable or disable session recording"""
        try:
            self._song.session_record = on
            return {"session_record": self._song.session_record}
        except Exception as e:
            self.log_message("Error setting session record: " + str(e))
            raise

    def _set_session_automation_record(self, on):
        """Enable or disable session automation recording"""
        try:
            self._song.session_automation_record = on
            return {"session_automation_record": self._song.session_automation_record}
        except Exception as e:
            self.log_message("Error setting session automation record: " + str(e))
            raise

    def _re_enable_automation(self):
        """Re-enable automation after manual override"""
        try:
            self._song.re_enable_automation()
            return {"re_enabled": True}
        except Exception as e:
            self.log_message("Error re-enabling automation: " + str(e))
            raise

    def _set_punch_in(self, on):
        """Enable or disable punch in"""
        try:
            self._song.punch_in = on
            return {"punch_in": self._song.punch_in}
        except Exception as e:
            self.log_message("Error setting punch in: " + str(e))
            raise

    def _set_punch_out(self, on):
        """Enable or disable punch out"""
        try:
            self._song.punch_out = on
            return {"punch_out": self._song.punch_out}
        except Exception as e:
            self.log_message("Error setting punch out: " + str(e))
            raise

    def _set_exclusive_arm(self, on):
        """Enable or disable exclusive arm"""
        try:
            self._song.exclusive_arm = on
            return {"exclusive_arm": self._song.exclusive_arm}
        except Exception as e:
            self.log_message("Error setting exclusive arm: " + str(e))
            raise

    def _create_return_track(self):
        """Create a new return track"""
        try:
            self._song.create_return_track()
            return {
                "return_track_count": len(self._song.return_tracks),
                "name": self._song.return_tracks[-1].name
            }
        except Exception as e:
            self.log_message("Error creating return track: " + str(e))
            raise

    def _delete_return_track(self, index):
        """Delete a return track by index"""
        try:
            if index < 0 or index >= len(self._song.return_tracks):
                raise IndexError("Return track index out of range")
            self._song.delete_return_track(index)
            return {"return_track_count": len(self._song.return_tracks)}
        except Exception as e:
            self.log_message("Error deleting return track: " + str(e))
            raise

    def _set_track_color(self, track_index, color_index):
        """Set track color by color index"""
        try:
            track = self._get_track(track_index)
            track.color_index = color_index
            return {"color_index": track.color_index}
        except Exception as e:
            self.log_message("Error setting track color: " + str(e))
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

    def _set_track_input_routing(self, track_index, routing_type_name):
        """Set track input routing by name"""
        try:
            track = self._get_track(track_index)
            for routing_type in track.available_input_routing_types:
                name = str(routing_type.display_name) if hasattr(routing_type, 'display_name') else str(routing_type)
                if name == routing_type_name:
                    track.input_routing_type = routing_type
                    return {"input_routing_type": routing_type_name}
            raise Exception("Routing type not found: " + routing_type_name)
        except Exception as e:
            self.log_message("Error setting track input routing: " + str(e))
            raise

    def _set_track_output_routing(self, track_index, routing_type_name):
        """Set track output routing by name"""
        try:
            track = self._get_track(track_index)
            for routing_type in track.available_output_routing_types:
                name = str(routing_type.display_name) if hasattr(routing_type, 'display_name') else str(routing_type)
                if name == routing_type_name:
                    track.output_routing_type = routing_type
                    return {"output_routing_type": routing_type_name}
            raise Exception("Routing type not found: " + routing_type_name)
        except Exception as e:
            self.log_message("Error setting track output routing: " + str(e))
            raise

    def _fold_track(self, track_index, fold):
        """Fold or unfold a group track"""
        try:
            track = self._get_track(track_index)
            if not track.is_foldable:
                raise Exception("Track is not a group track")
            track.fold_state = 1 if fold else 0
            return {"fold_state": track.fold_state}
        except Exception as e:
            self.log_message("Error folding track: " + str(e))
            raise

    def _set_scene_color(self, scene_index, color_index):
        """Set scene color by color index"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene = self._song.scenes[scene_index]
            scene.color_index = color_index
            return {"color_index": scene.color_index}
        except Exception as e:
            self.log_message("Error setting scene color: " + str(e))
            raise

    def _duplicate_scene(self, scene_index):
        """Duplicate a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            self._song.duplicate_scene(scene_index)
            return {"scene_count": len(self._song.scenes)}
        except Exception as e:
            self.log_message("Error duplicating scene: " + str(e))
            raise

    def _set_crossfader(self, position):
        """Set crossfader position (0.0 to 1.0, 0.5 = center)"""
        try:
            cf = self._song.master_track.mixer_device.crossfader
            actual_value = cf.min + position * (cf.max - cf.min)
            cf.value = actual_value
            return {"crossfader": cf.value, "normalized": position}
        except Exception as e:
            self.log_message("Error setting crossfader: " + str(e))
            raise

    def _set_crossfade_assign(self, track_index, assign):
        """Set crossfade assignment (0=None, 1=A, 2=B)"""
        try:
            track = self._get_track(track_index)
            track.mixer_device.crossfade_assign = assign
            return {"crossfade_assign": track.mixer_device.crossfade_assign}
        except Exception as e:
            self.log_message("Error setting crossfade assign: " + str(e))
            raise

    def _set_cue_volume(self, volume):
        """Set cue/preview volume (0.0 to 1.0)"""
        try:
            cue = self._song.master_track.mixer_device.cue_volume
            actual_value = cue.min + volume * (cue.max - cue.min)
            cue.value = actual_value
            return {"cue_volume": cue.value, "normalized": volume}
        except Exception as e:
            self.log_message("Error setting cue volume: " + str(e))
            raise

    def _set_device_enabled(self, track_index, device_index, enabled):
        """Enable or disable a device"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if hasattr(device, 'is_active'):
                # is_active is read-only in some versions; use parameters[0] which is usually "Device On"
                pass
            # The standard way to enable/disable is through the first parameter
            for param in device.parameters:
                if param.name == "Device On":
                    param.value = 1.0 if enabled else 0.0
                    return {"enabled": enabled, "device_name": device.name}
            raise Exception("Device does not have an on/off parameter")
        except Exception as e:
            self.log_message("Error setting device enabled: " + str(e))
            raise

    def _get_drum_pads(self, track_index, device_index):
        """Get drum pad info from a Drum Rack"""
        try:
            track = self._get_track(track_index)
            if device_index < 0 or device_index >= len(track.devices):
                raise IndexError("Device index out of range")
            device = track.devices[device_index]
            if not hasattr(device, 'drum_pads'):
                raise Exception("Device is not a Drum Rack")
            pads = []
            for pad in device.drum_pads:
                pad_info = {
                    "note": pad.note,
                    "name": pad.name,
                    "mute": pad.mute,
                    "solo": pad.solo,
                }
                if hasattr(pad, 'chains') and len(pad.chains) > 0:
                    pad_info["has_device"] = True
                    if len(pad.chains[0].devices) > 0:
                        pad_info["device_name"] = pad.chains[0].devices[0].name
                else:
                    pad_info["has_device"] = False
                pads.append(pad_info)
            filled_pads = [p for p in pads if p.get("has_device", False)]
            return {"pads": filled_pads, "total_pads": len(pads)}
        except Exception as e:
            self.log_message("Error getting drum pads: " + str(e))
            raise

    def _set_scale(self, name=None, root_note=None):
        """Set the global scale"""
        try:
            result = {}
            if name is not None and hasattr(self._song, 'scale_name'):
                self._song.scale_name = name
                result["scale_name"] = self._song.scale_name
            if root_note is not None and hasattr(self._song, 'root_note'):
                self._song.root_note = root_note
                result["root_note"] = self._song.root_note
            return result
        except Exception as e:
            self.log_message("Error setting scale: " + str(e))
            raise

    def _get_cue_points(self):
        """Get all cue points"""
        try:
            cue_points = []
            if hasattr(self._song, 'cue_points'):
                for cp in self._song.cue_points:
                    cue_points.append({
                        "time": cp.time,
                        "name": cp.name if hasattr(cp, 'name') else ""
                    })
            return {"cue_points": cue_points}
        except Exception as e:
            self.log_message("Error getting cue points: " + str(e))
            raise

    def _get_scene_info(self, scene_index):
        """Get detailed info about a scene"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene = self._song.scenes[scene_index]
            result = {
                "index": scene_index,
                "name": scene.name,
                "color": scene.color,
                "color_index": scene.color_index,
                "tempo": scene.tempo if hasattr(scene, 'tempo') else 0,
                "is_triggered": scene.is_triggered,
            }
            if hasattr(scene, 'clip_slots'):
                clips = []
                for i, slot in enumerate(scene.clip_slots):
                    if slot.has_clip:
                        clips.append({"track_index": i, "clip_name": slot.clip.name})
                result["clips"] = clips
            return result
        except Exception as e:
            self.log_message("Error getting scene info: " + str(e))
            raise

    def _set_scene_tempo(self, scene_index, tempo):
        """Set scene tempo"""
        try:
            if scene_index < 0 or scene_index >= len(self._song.scenes):
                raise IndexError("Scene index out of range")
            scene = self._song.scenes[scene_index]
            scene.tempo = tempo
            return {"tempo": scene.tempo}
        except Exception as e:
            self.log_message("Error setting scene tempo: " + str(e))
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
                parameters.append({
                    "index": i,
                    "name": p.name,
                    "value": p.value,
                    "normalized_value": norm_val,
                    "min": p.min,
                    "max": p.max,
                    "is_quantized": p.is_quantized,
                    "is_enabled": p.is_enabled
                })
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
    
    def _create_audio_clip(self, track_index, clip_index, file_path):
        """Create an audio clip from a file path in a clip slot on an audio track."""
        try:
            if track_index < 0 or track_index >= len(self._song.tracks):
                raise IndexError("Track index out of range")

            track = self._song.tracks[track_index]

            if not track.has_audio_input:
                raise Exception("Track {0} is not an audio track".format(track_index))

            if clip_index < 0 or clip_index >= len(track.clip_slots):
                raise IndexError("Clip index out of range")

            clip_slot = track.clip_slots[clip_index]

            if clip_slot.has_clip:
                raise Exception("Clip slot already has a clip")

            # Create audio clip from file path
            clip_slot.create_clip(file_path)

            clip = clip_slot.clip
            result = {
                "name": clip.name if clip else "unknown",
                "length": clip.length if clip else 0,
                "file_path": file_path,
                "track_index": track_index,
                "clip_index": clip_index
            }
            return result
        except Exception as e:
            self.log_message("Error creating audio clip: " + str(e))
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
    
    def _set_clip_name(self, track_index, clip_index, name):
        """Set the name of a clip"""
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
            self._song.back_to_arranger = True
            if time is not None:
                self._song.current_song_time = float(time)
            self._song.start_playing()
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
