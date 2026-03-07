# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import socket
import json
import logging
from dataclasses import dataclass
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict, Any, List, Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks.
        Uses whatever timeout is already set on the socket."""
        chunks = []
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "create_clip", "create_audio_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "batch_set_device_parameters",
            "start_playback", "stop_playback", "load_instrument_or_effect",
            "load_browser_item", "set_track_volume", "set_track_panning",
            "fire_scene", "set_song_time", "set_record_mode",
            "set_arrangement_overdub", "set_back_to_arranger",
            "set_arrangement_loop",
            "set_track_mute", "set_track_solo",
            "delete_clip", "duplicate_clip",
            "create_scene", "delete_scene", "set_scene_name",
            "delete_track", "record_arrangement",
            "delete_device", "duplicate_track", "set_clip_loop",
            "set_track_arm", "set_send_level", "set_time_signature", "set_metronome",
            "set_clip_envelope", "clear_clip_envelope",
            "undo", "redo"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            # Set timeout based on command type
            if command_type == "record_arrangement":
                timeout = 600.0  # 10 minutes for arrangement recording
            elif is_modifying_command:
                timeout = 15.0
            else:
                timeout = 10.0
            self.sock.settimeout(timeout)
            
            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")
            
            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")
            
            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))
            
            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                import time
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    # description="Ableton Live integration through the Model Context Protocol",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Test the connection with a simple ping
            # We'll try to send an empty message, which should fail if the connection is dead
            # but won't affect Ableton if it's alive
            _ableton_connection.sock.settimeout(1.0)
            _ableton_connection.sock.sendall(b'')
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                import time
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


# Core Tool endpoints

@mcp.tool()
def get_session_info(ctx: Context) -> str:
    """Get detailed information about the current Ableton session"""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_session_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.
    
    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_info", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.
    
    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.
    
    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.
    
    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_clip", {
            "track_index": track_index, 
            "clip_index": clip_index, 
            "length": length
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
def create_audio_clip(ctx: Context, track_index: int, clip_index: int, file_path: str) -> str:
    """
    Create an audio clip from a file path in a clip slot on an audio track.

    Parameters:
    - track_index: The index of the audio track
    - clip_index: The index of the clip slot
    - file_path: Absolute path to an audio file (wav, aiff, flac, mp3, etc.)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "file_path": file_path
        })
        return f"Created audio clip '{result.get('name', '')}' (length: {result.get('length', 0)} beats) at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error creating audio clip: {str(e)}")
        return f"Error creating audio clip: {str(e)}"

@mcp.tool()
def add_notes_to_clip(
    ctx: Context, 
    track_index: int, 
    clip_index: int, 
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.
    
    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
def get_device_parameters(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Get all parameters of a device on a track, including their current values and ranges.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_device_parameters", {
            "track_index": track_index,
            "device_index": device_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
def set_device_parameter(ctx: Context, track_index: int, device_index: int, parameter_index: int, value: float) -> str:
    """
    Set a device parameter using a normalized value (0.0 to 1.0).
    Use get_device_parameters first to see available parameters and their indices.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_index: The index of the parameter to set
    - value: Normalized value between 0.0 and 1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "value": value
        })
        param_name = result.get("parameter_name", "unknown")
        actual_value = result.get("value", value)
        return f"Set '{param_name}' to {actual_value} (normalized: {value})"
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"

@mcp.tool()
def batch_set_device_parameters(ctx: Context, track_index: int, device_index: int, parameter_indices: List[int], values: List[float]) -> str:
    """
    Set multiple device parameters at once using normalized values (0.0 to 1.0).
    Use get_device_parameters first to see available parameters and their indices.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_indices: List of parameter indices to set
    - values: List of normalized values (0.0 to 1.0), must match length of parameter_indices
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("batch_set_device_parameters", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_indices": parameter_indices,
            "values": values
        })
        updated_count = result.get("updated_count", 0)
        params = result.get("parameters", [])
        details = ", ".join([f"{p['name']}={p['value']:.2f}" for p in params])
        return f"Updated {updated_count} parameters: {details}"
    except Exception as e:
        logger.error(f"Error batch setting device parameters: {str(e)}")
        return f"Error batch setting device parameters: {str(e)}"

@mcp.tool()
def load_instrument_or_effect(ctx: Context, track_index: int, uri: str, clip_index: int = -1) -> str:
    """
    Load an instrument or effect onto a track using its URI.
    Use track_index -1 for the master track.

    Parameters:
    - track_index: The index of the track to load on (-1 for master)
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    - clip_index: Optional clip slot index to select before loading (needed for .alc audio clips). Default -1 means no clip slot selection.
    """
    try:
        ableton = get_ableton_connection()
        cmd_params = {
            "track_index": track_index,
            "item_uri": uri
        }
        if clip_index >= 0:
            cmd_params["clip_index"] = clip_index
        result = ableton.send_command("load_browser_item", cmd_params)
        
        # Check if the instrument was loaded successfully
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            else:
                devices = result.get("devices_after", [])
                return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        else:
            return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.
    
    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
def play_arrangement(ctx: Context, time: float = 0.0) -> str:
    """Play the arrangement from a specific position. Stops all session clips and switches to arrangement view.

    Parameters:
    - time: Position in beats to start from (0.0 = start). Default 0.0.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("play_arrangement", {"time": time})
        return f"Playing arrangement from beat {time}"
    except Exception as e:
        logger.error(f"Error playing arrangement: {str(e)}")
        return f"Error playing arrangement: {str(e)}"

@mcp.tool()
def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.
    
    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_tree", {
            "category_type": category_type
        })
        
        # Check if we got any categories
        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                   f"Available browser categories: {', '.join(available_cats)}")
        
        # Format the tree in a more readable way
        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"
        
        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                
                # Add this item
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                
                # Add children
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output
        
        # Format each category
        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"
        
        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.
    
    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_browser_items_at_path", {
            "path": path
        })
        
        # Check if there was an error with available categories
        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                   f"Available browser categories: {', '.join(available_cats)}")
        
        return json.dumps(result, indent=2)
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return f"Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return f"Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.
    
    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        ableton = get_ableton_connection()
        
        # Step 1: Load the drum rack
        result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": rack_uri
        })
        
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"
        
        # Step 2: Get the drum kit items at the specified path
        kit_result = ableton.send_command("get_browser_items_at_path", {
            "path": kit_path
        })
        
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"
        
        # Step 3: Find a loadable drum kit
        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"
        
        # Step 4: Load the first loadable kit
        kit_uri = loadable_kits[0].get("uri")
        load_result = ableton.send_command("load_browser_item", {
            "track_index": track_index,
            "item_uri": kit_uri
        })
        
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

@mcp.tool()
def set_track_volume(ctx: Context, track_index: int, volume: float) -> str:
    """
    Set a track's volume level using a normalized value (0.0 to 1.0).
    Use track_index -1 for the master track.

    Parameters:
    - track_index: The index of the track (-1 for master)
    - volume: Normalized volume value (0.0 = silent, 0.85 = default, 1.0 = max)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_volume", {
            "track_index": track_index,
            "volume": volume
        })
        track_name = result.get("track_name", "unknown")
        return f"Set '{track_name}' volume to {volume:.2f}"
    except Exception as e:
        logger.error(f"Error setting track volume: {str(e)}")
        return f"Error setting track volume: {str(e)}"

@mcp.tool()
def set_track_panning(ctx: Context, track_index: int, panning: float) -> str:
    """
    Set a track's panning using a normalized value (0.0 to 1.0, where 0.5 is center).
    Use track_index -1 for the master track.

    Parameters:
    - track_index: The index of the track (-1 for master)
    - panning: Normalized panning value (0.0 = full left, 0.5 = center, 1.0 = full right)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_panning", {
            "track_index": track_index,
            "panning": panning
        })
        track_name = result.get("track_name", "unknown")
        return f"Set '{track_name}' panning to {panning:.2f}"
    except Exception as e:
        logger.error(f"Error setting track panning: {str(e)}")
        return f"Error setting track panning: {str(e)}"

@mcp.tool()
def get_arrangement_info(ctx: Context) -> str:
    """Get current arrangement state including song time, record mode, loop settings, and transport status."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_info")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement info: {str(e)}")
        return f"Error getting arrangement info: {str(e)}"

@mcp.tool()
def fire_scene(ctx: Context, scene_index: int) -> str:
    """
    Fire (launch) all clips in a scene at once.

    Parameters:
    - scene_index: The index of the scene to fire
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fire_scene", {
            "scene_index": scene_index
        })
        scene_name = result.get("scene_name", "")
        return f"Fired scene {scene_index}" + (f" ({scene_name})" if scene_name else "")
    except Exception as e:
        logger.error(f"Error firing scene: {str(e)}")
        return f"Error firing scene: {str(e)}"

@mcp.tool()
def set_song_time(ctx: Context, time: float) -> str:
    """
    Set the current song time (arrangement playback position) in beats.

    Parameters:
    - time: Position in beats (0.0 = start, 4.0 = bar 2, etc.)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_song_time", {
            "time": time
        })
        return f"Set song time to {result.get('current_song_time', time):.1f} beats"
    except Exception as e:
        logger.error(f"Error setting song time: {str(e)}")
        return f"Error setting song time: {str(e)}"

@mcp.tool()
def set_record_mode(ctx: Context, on: bool) -> str:
    """
    Enable or disable arrangement recording.
    When enabled, session clip playback is recorded into the arrangement.

    Parameters:
    - on: True to start recording, False to stop
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_record_mode", {
            "on": on
        })
        state = "enabled" if on else "disabled"
        return f"Arrangement recording {state}"
    except Exception as e:
        logger.error(f"Error setting record mode: {str(e)}")
        return f"Error setting record mode: {str(e)}"

@mcp.tool()
def set_arrangement_overdub(ctx: Context, on: bool) -> str:
    """
    Enable or disable arrangement overdub.
    When enabled, new recordings are layered on top of existing arrangement clips.

    Parameters:
    - on: True to enable overdub, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_overdub", {
            "on": on
        })
        state = "enabled" if result.get("arrangement_overdub") else "disabled"
        return f"Arrangement overdub {state}"
    except Exception as e:
        logger.error(f"Error setting arrangement overdub: {str(e)}")
        return f"Error setting arrangement overdub: {str(e)}"

@mcp.tool()
def set_back_to_arranger(ctx: Context) -> str:
    """Return playback to the arrangement view from session view."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_back_to_arranger")
        return "Returned to arrangement"
    except Exception as e:
        logger.error(f"Error setting back to arranger: {str(e)}")
        return f"Error setting back to arranger: {str(e)}"

@mcp.tool()
def set_arrangement_loop(ctx: Context, on: bool, start: float = 0.0, length: float = 16.0) -> str:
    """
    Set arrangement loop on/off, start position and length.

    Parameters:
    - on: True to enable loop, False to disable
    - start: Loop start position in beats
    - length: Loop length in beats (e.g. 16.0 = 4 bars)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_arrangement_loop", {
            "on": on,
            "start": start,
            "length": length
        })
        if on:
            return f"Loop enabled: start={result.get('loop_start', start):.1f}, length={result.get('loop_length', length):.1f} beats"
        else:
            return "Loop disabled"
    except Exception as e:
        logger.error(f"Error setting arrangement loop: {str(e)}")
        return f"Error setting arrangement loop: {str(e)}"

@mcp.tool()
def set_track_mute(ctx: Context, track_index: int, mute: bool) -> str:
    """
    Mute or unmute a track.

    Parameters:
    - track_index: The index of the track (-1 for master)
    - mute: True to mute, False to unmute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_mute", {
            "track_index": track_index,
            "mute": mute
        })
        track_name = result.get("track_name", "unknown")
        state = "muted" if mute else "unmuted"
        return f"Track '{track_name}' {state}"
    except Exception as e:
        logger.error(f"Error setting track mute: {str(e)}")
        return f"Error setting track mute: {str(e)}"

@mcp.tool()
def set_track_solo(ctx: Context, track_index: int, solo: bool) -> str:
    """
    Solo or unsolo a track.

    Parameters:
    - track_index: The index of the track
    - solo: True to solo, False to unsolo
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_solo", {
            "track_index": track_index,
            "solo": solo
        })
        track_name = result.get("track_name", "unknown")
        state = "soloed" if solo else "unsoloed"
        return f"Track '{track_name}' {state}"
    except Exception as e:
        logger.error(f"Error setting track solo: {str(e)}")
        return f"Error setting track solo: {str(e)}"

@mcp.tool()
def delete_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Delete a clip from a clip slot.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_clip", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return f"Deleted clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error deleting clip: {str(e)}")
        return f"Error deleting clip: {str(e)}"

@mcp.tool()
def duplicate_clip(ctx: Context, track_index: int, clip_index: int, target_index: int = -1) -> str:
    """
    Duplicate a clip to another slot on the same track.

    Parameters:
    - track_index: The index of the track
    - clip_index: The source clip slot index
    - target_index: The target clip slot index (-1 to auto-find next empty slot)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "target_index": target_index
        })
        target = result.get("target_index", target_index)
        return f"Duplicated clip from slot {clip_index} to slot {target} on track {track_index}"
    except Exception as e:
        logger.error(f"Error duplicating clip: {str(e)}")
        return f"Error duplicating clip: {str(e)}"

@mcp.tool()
def create_scene(ctx: Context, index: int = -1) -> str:
    """
    Create a new scene at the specified index.

    Parameters:
    - index: Position to insert the scene (-1 to add at the end)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_scene", {
            "index": index
        })
        return f"Created scene at index {result.get('scene_index', index)} (total: {result.get('scene_count', '?')} scenes)"
    except Exception as e:
        logger.error(f"Error creating scene: {str(e)}")
        return f"Error creating scene: {str(e)}"

@mcp.tool()
def set_scene_name(ctx: Context, scene_index: int, name: str) -> str:
    """
    Set a scene's name (e.g. "Intro", "Drop", "Outro").

    Parameters:
    - scene_index: The index of the scene
    - name: The name to set
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_name", {
            "scene_index": scene_index,
            "name": name
        })
        return f"Set scene {scene_index} name to '{result.get('name', name)}'"
    except Exception as e:
        logger.error(f"Error setting scene name: {str(e)}")
        return f"Error setting scene name: {str(e)}"

@mcp.tool()
def create_audio_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new audio track at the specified index.

    Parameters:
    - index: Position to insert the track (-1 to add at the end)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_audio_track", {
            "index": index
        })
        return f"Created audio track '{result.get('name', '')}' at index {result.get('index', index)}"
    except Exception as e:
        logger.error(f"Error creating audio track: {str(e)}")
        return f"Error creating audio track: {str(e)}"

@mcp.tool()
def delete_track(ctx: Context, track_index: int) -> str:
    """
    Delete a track.

    Parameters:
    - track_index: The index of the track to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_track", {
            "track_index": track_index
        })
        return f"Deleted track '{result.get('deleted_track', '')}' (remaining: {result.get('track_count', '?')} tracks)"
    except Exception as e:
        logger.error(f"Error deleting track: {str(e)}")
        return f"Error deleting track: {str(e)}"

@mcp.tool()
def get_arrangement_clips(ctx: Context, track_index: int) -> str:
    """
    Get arrangement clips for a track. Shows what clips are in the arrangement timeline.
    Use track_index -1 for master track.

    Parameters:
    - track_index: The index of the track
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_arrangement_clips", {
            "track_index": track_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"

@mcp.tool()
def record_arrangement(ctx: Context, sections: List[dict]) -> str:
    """
    Record session clips into the arrangement by firing scenes at timed intervals.
    This runs inside Ableton for precise timing. Handles seeking, recording, and stopping automatically.

    Parameters:
    - sections: List of {"scene_index": int, "bars": int} defining each section.
                Example: [{"scene_index": 0, "bars": 8}, {"scene_index": 1, "bars": 8}, {"scene_index": 2, "bars": 16}]
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("record_arrangement", {
            "sections": sections
        })
        total_bars = result.get("total_bars", 0)
        tempo = result.get("tempo", 120)
        recorded = result.get("sections", [])
        summary = []
        for s in recorded:
            summary.append(f"  Bars {s['start_bar']}-{s['end_bar']}: Scene {s['scene_index']} ({s['scene_name']}) [{s['bars']} bars]")
        return f"Recorded {total_bars} bars at {tempo} BPM:\n" + "\n".join(summary)
    except Exception as e:
        logger.error(f"Error recording arrangement: {str(e)}")
        return f"Error recording arrangement: {str(e)}"

@mcp.tool()
def get_full_arrangement(ctx: Context) -> str:
    """
    Get a complete view of the arrangement — all tracks with their arrangement clips,
    song tempo, time signature, length, and scene list.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_full_arrangement", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting full arrangement: {str(e)}")
        return f"Error getting full arrangement: {str(e)}"

@mcp.tool()
def delete_scene(ctx: Context, scene_index: int) -> str:
    """
    Delete a scene.

    Parameters:
    - scene_index: The index of the scene to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_scene", {
            "scene_index": scene_index
        })
        return f"Deleted scene '{result.get('deleted_scene', '')}' (remaining: {result.get('scene_count', '?')} scenes)"
    except Exception as e:
        logger.error(f"Error deleting scene: {str(e)}")
        return f"Error deleting scene: {str(e)}"

@mcp.tool()
def delete_device(ctx: Context, track_index: int, device_index: int) -> str:
    """
    Delete a device from a track.

    Parameters:
    - track_index: The index of the track (use -1 for master, -2/-3 for returns)
    - device_index: The index of the device to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_device", {
            "track_index": track_index,
            "device_index": device_index
        })
        return f"Deleted device '{result.get('deleted_device', '')}' ({result.get('device_count', '?')} devices remaining)"
    except Exception as e:
        logger.error(f"Error deleting device: {str(e)}")
        return f"Error deleting device: {str(e)}"

@mcp.tool()
def duplicate_track(ctx: Context, track_index: int) -> str:
    """
    Duplicate a track (creates a copy with all clips and devices).

    Parameters:
    - track_index: The index of the track to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_track", {
            "track_index": track_index
        })
        return f"Duplicated '{result.get('original_track', '')}' → new track '{result.get('new_track_name', '')}' at index {result.get('new_track_index', '?')}"
    except Exception as e:
        logger.error(f"Error duplicating track: {str(e)}")
        return f"Error duplicating track: {str(e)}"

@mcp.tool()
def set_clip_loop(ctx: Context, track_index: int, clip_index: int, loop_start: float = None, loop_end: float = None, looping: bool = None) -> str:
    """
    Set clip loop settings. All parameters are optional — only provided values are changed.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - loop_start: Loop start position in beats (optional)
    - loop_end: Loop end position in beats (optional)
    - looping: Whether the clip should loop (optional)
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if loop_start is not None:
            params["loop_start"] = loop_start
        if loop_end is not None:
            params["loop_end"] = loop_end
        if looping is not None:
            params["looping"] = looping
        result = ableton.send_command("set_clip_loop", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting clip loop: {str(e)}")
        return f"Error setting clip loop: {str(e)}"

@mcp.tool()
def get_clip_notes(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Get all MIDI notes from a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_notes", {
            "track_index": track_index,
            "clip_index": clip_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip notes: {str(e)}")
        return f"Error getting clip notes: {str(e)}"

@mcp.tool()
def set_track_arm(ctx: Context, track_index: int, arm: bool) -> str:
    """
    Arm or disarm a track for recording.

    Parameters:
    - track_index: The index of the track
    - arm: True to arm, False to disarm
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_arm", {
            "track_index": track_index,
            "arm": arm
        })
        state = "armed" if result.get("arm") else "disarmed"
        return f"Track '{result.get('track_name', '')}' {state}"
    except Exception as e:
        logger.error(f"Error setting track arm: {str(e)}")
        return f"Error setting track arm: {str(e)}"

@mcp.tool()
def set_send_level(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set the send level for a track.

    Parameters:
    - track_index: The index of the track (use -1 for master, -2/-3 for returns)
    - send_index: The index of the send (0 = Send A, 1 = Send B, etc.)
    - value: Normalized value 0.0-1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_send_level", {
            "track_index": track_index,
            "send_index": send_index,
            "value": value
        })
        return f"Set send {send_index} on track {track_index} to {value}"
    except Exception as e:
        logger.error(f"Error setting send level: {str(e)}")
        return f"Error setting send level: {str(e)}"

@mcp.tool()
def set_time_signature(ctx: Context, numerator: int, denominator: int) -> str:
    """
    Set the song time signature.

    Parameters:
    - numerator: Time signature numerator (e.g., 4 for 4/4)
    - denominator: Time signature denominator (e.g., 4 for 4/4)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_time_signature", {
            "numerator": numerator,
            "denominator": denominator
        })
        return f"Set time signature to {result.get('numerator', numerator)}/{result.get('denominator', denominator)}"
    except Exception as e:
        logger.error(f"Error setting time signature: {str(e)}")
        return f"Error setting time signature: {str(e)}"

@mcp.tool()
def set_metronome(ctx: Context, on: bool) -> str:
    """
    Enable or disable the metronome.

    Parameters:
    - on: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_metronome", {"on": on})
        state = "enabled" if result.get("metronome") else "disabled"
        return f"Metronome {state}"
    except Exception as e:
        logger.error(f"Error setting metronome: {str(e)}")
        return f"Error setting metronome: {str(e)}"

@mcp.tool()
def set_clip_envelope(ctx: Context, track_index: int, clip_index: int, device_index: int, parameter_index: int, points: List[dict]) -> str:
    """
    Set automation envelope points for a parameter in a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - device_index: The index of the device
    - parameter_index: The index of the parameter
    - points: List of {"time": float, "value": float} where value is normalized 0.0-1.0
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_envelope", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index,
            "points": points
        })
        return f"Set {result.get('points_set', 0)} automation points for '{result.get('parameter_name', '')}'"
    except Exception as e:
        logger.error(f"Error setting clip envelope: {str(e)}")
        return f"Error setting clip envelope: {str(e)}"

@mcp.tool()
def get_clip_envelope(ctx: Context, track_index: int, clip_index: int, device_index: int, parameter_index: int) -> str:
    """
    Read automation envelope data for a parameter in a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - device_index: The index of the device
    - parameter_index: The index of the parameter
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_envelope", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip envelope: {str(e)}")
        return f"Error getting clip envelope: {str(e)}"

@mcp.tool()
def clear_clip_envelope(ctx: Context, track_index: int, clip_index: int, device_index: int, parameter_index: int) -> str:
    """
    Clear automation envelope for a parameter in a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - device_index: The index of the device
    - parameter_index: The index of the parameter
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("clear_clip_envelope", {
            "track_index": track_index,
            "clip_index": clip_index,
            "device_index": device_index,
            "parameter_index": parameter_index
        })
        return f"Cleared automation for '{result.get('parameter_name', '')}'"
    except Exception as e:
        logger.error(f"Error clearing clip envelope: {str(e)}")
        return f"Error clearing clip envelope: {str(e)}"

@mcp.tool()
def undo(ctx: Context) -> str:
    """Undo the last action in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("undo", {})
        return "Undone"
    except Exception as e:
        logger.error(f"Error undoing: {str(e)}")
        return f"Error undoing: {str(e)}"

@mcp.tool()
def redo(ctx: Context) -> str:
    """Redo the last undone action in Ableton."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("redo", {})
        return "Redone"
    except Exception as e:
        logger.error(f"Error redoing: {str(e)}")
        return f"Error redoing: {str(e)}"

# ============ CLIP OPERATIONS ============

@mcp.tool()
def get_clip_info(ctx: Context, track_index: int, clip_index: int) -> str:
    """Get detailed information about a specific clip including color, launch mode, warping, and audio properties.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_clip_info", {"track_index": track_index, "clip_index": clip_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting clip info: {str(e)}")
        return f"Error getting clip info: {str(e)}"

@mcp.tool()
def remove_notes(ctx: Context, track_index: int, clip_index: int, from_pitch: int = 0, pitch_span: int = 128, from_time: float = 0.0, time_span: float = -1.0) -> str:
    """Remove MIDI notes from a clip within a pitch and time range.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - from_pitch: Start pitch (0-127, default 0)
    - pitch_span: Number of pitches to span (default 128 = all)
    - from_time: Start time in beats (default 0.0)
    - time_span: Time span in beats (default -1 = entire clip)
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index, "from_pitch": from_pitch, "pitch_span": pitch_span, "from_time": from_time, "time_span": time_span}
        result = ableton.send_command("remove_notes", params)
        return f"Removed notes from clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error removing notes: {str(e)}")
        return f"Error removing notes: {str(e)}"

@mcp.tool()
def quantize_clip(ctx: Context, track_index: int, clip_index: int, grid: int = 4, strength: float = 1.0) -> str:
    """Quantize notes in a clip to a grid.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - grid: Quantization grid (1=1/4, 2=1/8, 3=1/16, 4=1/32, etc.)
    - strength: Quantization strength (0.0 to 1.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("quantize_clip", {"track_index": track_index, "clip_index": clip_index, "grid": grid, "strength": strength})
        return f"Quantized clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error quantizing clip: {str(e)}")
        return f"Error quantizing clip: {str(e)}"

@mcp.tool()
def duplicate_clip_loop(ctx: Context, track_index: int, clip_index: int) -> str:
    """Double the loop length and duplicate contents of a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_clip_loop", {"track_index": track_index, "clip_index": clip_index})
        return f"Duplicated loop. New length: {result.get('new_length', 'unknown')} beats"
    except Exception as e:
        logger.error(f"Error duplicating clip loop: {str(e)}")
        return f"Error duplicating clip loop: {str(e)}"

@mcp.tool()
def duplicate_region(ctx: Context, track_index: int, clip_index: int, region_start: float, region_length: float, destination_time: float, pitch: int = -1, transposition_amount: int = 0) -> str:
    """Duplicate a region within a MIDI clip, optionally transposing.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - region_start: Start time of region in beats
    - region_length: Length of region in beats
    - destination_time: Where to paste the duplicated region
    - pitch: Specific pitch to duplicate (-1 = all pitches)
    - transposition_amount: Semitones to transpose (0 = no transposition)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_region", {"track_index": track_index, "clip_index": clip_index, "region_start": region_start, "region_length": region_length, "destination_time": destination_time, "pitch": pitch, "transposition_amount": transposition_amount})
        return f"Duplicated region in clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error duplicating region: {str(e)}")
        return f"Error duplicating region: {str(e)}"

@mcp.tool()
def crop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """Crop clip to its loop boundaries, removing content outside.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("crop_clip", {"track_index": track_index, "clip_index": clip_index})
        return f"Cropped clip. New length: {result.get('length', 'unknown')} beats"
    except Exception as e:
        logger.error(f"Error cropping clip: {str(e)}")
        return f"Error cropping clip: {str(e)}"

@mcp.tool()
def set_clip_color(ctx: Context, track_index: int, clip_index: int, color_index: int) -> str:
    """Set the color of a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - color_index: Color index (0-69)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_color", {"track_index": track_index, "clip_index": clip_index, "color_index": color_index})
        return f"Set clip color to index {color_index}"
    except Exception as e:
        logger.error(f"Error setting clip color: {str(e)}")
        return f"Error setting clip color: {str(e)}"

@mcp.tool()
def set_clip_muted(ctx: Context, track_index: int, clip_index: int, muted: bool) -> str:
    """Mute or unmute a specific clip (not the track).

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - muted: True to mute, False to unmute
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_muted", {"track_index": track_index, "clip_index": clip_index, "muted": muted})
        return f"{'Muted' if muted else 'Unmuted'} clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error setting clip muted: {str(e)}")
        return f"Error setting clip muted: {str(e)}"

@mcp.tool()
def set_clip_launch_mode(ctx: Context, track_index: int, clip_index: int, launch_mode: int) -> str:
    """Set clip launch mode.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - launch_mode: 0=Trigger, 1=Gate, 2=Toggle, 3=Repeat
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_launch_mode", {"track_index": track_index, "clip_index": clip_index, "launch_mode": launch_mode})
        modes = {0: "Trigger", 1: "Gate", 2: "Toggle", 3: "Repeat"}
        return f"Set launch mode to {modes.get(launch_mode, str(launch_mode))}"
    except Exception as e:
        logger.error(f"Error setting launch mode: {str(e)}")
        return f"Error setting launch mode: {str(e)}"

@mcp.tool()
def set_clip_launch_quantization(ctx: Context, track_index: int, clip_index: int, quantization: int) -> str:
    """Set per-clip launch quantization.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - quantization: Quantization value (0=Global, 1=None, 2=8 bars, 3=4 bars, 4=2 bars, 5=1 bar, 6=1/2, etc.)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_launch_quantization", {"track_index": track_index, "clip_index": clip_index, "quantization": quantization})
        return f"Set clip launch quantization to {quantization}"
    except Exception as e:
        logger.error(f"Error setting launch quantization: {str(e)}")
        return f"Error setting launch quantization: {str(e)}"

@mcp.tool()
def set_clip_legato(ctx: Context, track_index: int, clip_index: int, legato: bool) -> str:
    """Enable or disable legato on a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - legato: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_legato", {"track_index": track_index, "clip_index": clip_index, "legato": legato})
        return f"{'Enabled' if legato else 'Disabled'} legato on clip"
    except Exception as e:
        logger.error(f"Error setting legato: {str(e)}")
        return f"Error setting legato: {str(e)}"

@mcp.tool()
def set_clip_start_marker(ctx: Context, track_index: int, clip_index: int, position: float) -> str:
    """Set the start marker position of a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - position: Position in beats
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_start_marker", {"track_index": track_index, "clip_index": clip_index, "position": position})
        return f"Set start marker to {position}"
    except Exception as e:
        logger.error(f"Error setting start marker: {str(e)}")
        return f"Error setting start marker: {str(e)}"

@mcp.tool()
def set_clip_end_marker(ctx: Context, track_index: int, clip_index: int, position: float) -> str:
    """Set the end marker position of a clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - position: Position in beats
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_end_marker", {"track_index": track_index, "clip_index": clip_index, "position": position})
        return f"Set end marker to {position}"
    except Exception as e:
        logger.error(f"Error setting end marker: {str(e)}")
        return f"Error setting end marker: {str(e)}"



# ============ AUDIO CLIP OPERATIONS ============

@mcp.tool()
def set_clip_warping(ctx: Context, track_index: int, clip_index: int, warping: bool) -> str:
    """Enable or disable warping on an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - warping: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_warping", {"track_index": track_index, "clip_index": clip_index, "warping": warping})
        return f"{'Enabled' if warping else 'Disabled'} warping"
    except Exception as e:
        logger.error(f"Error setting warping: {str(e)}")
        return f"Error setting warping: {str(e)}"

@mcp.tool()
def set_clip_warp_mode(ctx: Context, track_index: int, clip_index: int, warp_mode: int) -> str:
    """Set the warp mode of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - warp_mode: 0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 6=Complex Pro
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_warp_mode", {"track_index": track_index, "clip_index": clip_index, "warp_mode": warp_mode})
        modes = {0: "Beats", 1: "Tones", 2: "Texture", 3: "Re-Pitch", 4: "Complex", 6: "Complex Pro"}
        return f"Set warp mode to {modes.get(warp_mode, str(warp_mode))}"
    except Exception as e:
        logger.error(f"Error setting warp mode: {str(e)}")
        return f"Error setting warp mode: {str(e)}"

@mcp.tool()
def set_clip_gain(ctx: Context, track_index: int, clip_index: int, gain: float) -> str:
    """Set the gain of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - gain: Gain value (0.0 to 1.0 normalized)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_clip_gain", {"track_index": track_index, "clip_index": clip_index, "gain": gain})
        return f"Set clip gain to {gain} ({result.get('gain_display', '')})"
    except Exception as e:
        logger.error(f"Error setting clip gain: {str(e)}")
        return f"Error setting clip gain: {str(e)}"

@mcp.tool()
def set_clip_pitch(ctx: Context, track_index: int, clip_index: int, coarse: int = None, fine: int = None) -> str:
    """Set the pitch of an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - coarse: Pitch in semitones (-48 to 48)
    - fine: Fine pitch in cents (-500 to 500)
    """
    try:
        ableton = get_ableton_connection()
        params = {"track_index": track_index, "clip_index": clip_index}
        if coarse is not None:
            params["coarse"] = coarse
        if fine is not None:
            params["fine"] = fine
        result = ableton.send_command("set_clip_pitch", params)
        return f"Set pitch: coarse={result.get('pitch_coarse', 0)}, fine={result.get('pitch_fine', 0)}"
    except Exception as e:
        logger.error(f"Error setting clip pitch: {str(e)}")
        return f"Error setting clip pitch: {str(e)}"

@mcp.tool()
def get_warp_markers(ctx: Context, track_index: int, clip_index: int) -> str:
    """Get all warp markers from an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_warp_markers", {"track_index": track_index, "clip_index": clip_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting warp markers: {str(e)}")
        return f"Error getting warp markers: {str(e)}"

@mcp.tool()
def add_warp_marker(ctx: Context, track_index: int, clip_index: int, beat_time: float, sample_time: float) -> str:
    """Add a warp marker to an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - beat_time: Position in beats where the marker should be
    - sample_time: The sample time the marker should map to
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("add_warp_marker", {"track_index": track_index, "clip_index": clip_index, "beat_time": beat_time, "sample_time": sample_time})
        return f"Added warp marker at beat {beat_time}"
    except Exception as e:
        logger.error(f"Error adding warp marker: {str(e)}")
        return f"Error adding warp marker: {str(e)}"

@mcp.tool()
def move_warp_marker(ctx: Context, track_index: int, clip_index: int, beat_time: float, new_sample_time: float) -> str:
    """Move a warp marker in an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - beat_time: The beat time of the marker to move
    - new_sample_time: The new sample time for the marker
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("move_warp_marker", {"track_index": track_index, "clip_index": clip_index, "beat_time": beat_time, "new_sample_time": new_sample_time})
        return f"Moved warp marker at beat {beat_time}"
    except Exception as e:
        logger.error(f"Error moving warp marker: {str(e)}")
        return f"Error moving warp marker: {str(e)}"

@mcp.tool()
def delete_warp_marker(ctx: Context, track_index: int, clip_index: int, beat_time: float) -> str:
    """Delete a warp marker from an audio clip.

    Parameters:
    - track_index: The index of the track
    - clip_index: The index of the clip slot
    - beat_time: The beat time of the marker to delete
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_warp_marker", {"track_index": track_index, "clip_index": clip_index, "beat_time": beat_time})
        return f"Deleted warp marker at beat {beat_time}"
    except Exception as e:
        logger.error(f"Error deleting warp marker: {str(e)}")
        return f"Error deleting warp marker: {str(e)}"

# ============ SONG / TRANSPORT ============

@mcp.tool()
def capture_midi(ctx: Context) -> str:
    """Capture recently played MIDI into a clip (Ableton's Capture feature)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_midi")
        return "Captured MIDI"
    except Exception as e:
        logger.error(f"Error capturing MIDI: {str(e)}")
        return f"Error capturing MIDI: {str(e)}"

@mcp.tool()
def capture_and_insert_scene(ctx: Context) -> str:
    """Capture currently playing clips and insert them as a new scene."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("capture_and_insert_scene")
        return f"Captured scene. Total scenes: {result.get('scene_count', 'unknown')}"
    except Exception as e:
        logger.error(f"Error capturing scene: {str(e)}")
        return f"Error capturing scene: {str(e)}"

@mcp.tool()
def stop_all_clips(ctx: Context, quantized: bool = True) -> str:
    """Stop all playing clips.

    Parameters:
    - quantized: If True, clips stop at the next quantization point. If False, stop immediately.
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("stop_all_clips", {"quantized": quantized})
        return "Stopped all clips"
    except Exception as e:
        logger.error(f"Error stopping all clips: {str(e)}")
        return f"Error stopping all clips: {str(e)}"

@mcp.tool()
def tap_tempo(ctx: Context) -> str:
    """Tap tempo — call repeatedly to set tempo from tap timing."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("tap_tempo")
        return f"Tap tempo. Current tempo: {result.get('tempo', 'unknown')} BPM"
    except Exception as e:
        logger.error(f"Error tapping tempo: {str(e)}")
        return f"Error tapping tempo: {str(e)}"

@mcp.tool()
def jump_by(ctx: Context, amount: float) -> str:
    """Jump the playhead by a relative amount in beats.

    Parameters:
    - amount: Beats to jump (positive = forward, negative = backward)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_by", {"amount": amount})
        return f"Jumped to {result.get('current_song_time', 'unknown')} beats"
    except Exception as e:
        logger.error(f"Error jumping: {str(e)}")
        return f"Error jumping: {str(e)}"

@mcp.tool()
def set_or_delete_cue(ctx: Context) -> str:
    """Toggle a cue point at the current playhead position."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_or_delete_cue")
        return f"Toggled cue point at {result.get('current_song_time', 'unknown')}"
    except Exception as e:
        logger.error(f"Error with cue point: {str(e)}")
        return f"Error with cue point: {str(e)}"

@mcp.tool()
def jump_to_next_cue(ctx: Context) -> str:
    """Jump to the next cue point."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_to_next_cue")
        return f"Jumped to next cue at {result.get('current_song_time', 'unknown')}"
    except Exception as e:
        logger.error(f"Error jumping to next cue: {str(e)}")
        return f"Error jumping to next cue: {str(e)}"

@mcp.tool()
def jump_to_prev_cue(ctx: Context) -> str:
    """Jump to the previous cue point."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("jump_to_prev_cue")
        return f"Jumped to previous cue at {result.get('current_song_time', 'unknown')}"
    except Exception as e:
        logger.error(f"Error jumping to prev cue: {str(e)}")
        return f"Error jumping to prev cue: {str(e)}"

@mcp.tool()
def get_cue_points(ctx: Context) -> str:
    """Get all cue/locator points in the arrangement."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_cue_points")
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting cue points: {str(e)}")
        return f"Error getting cue points: {str(e)}"

@mcp.tool()
def set_swing_amount(ctx: Context, amount: float) -> str:
    """Set the global swing amount.

    Parameters:
    - amount: Swing amount (0.0 to 1.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_swing_amount", {"amount": amount})
        return f"Set swing amount to {amount}"
    except Exception as e:
        logger.error(f"Error setting swing: {str(e)}")
        return f"Error setting swing: {str(e)}"

@mcp.tool()
def set_groove_amount(ctx: Context, amount: float) -> str:
    """Set the global groove amount.

    Parameters:
    - amount: Groove amount (0.0 to 1.0)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_groove_amount", {"amount": amount})
        return f"Set groove amount to {amount}"
    except Exception as e:
        logger.error(f"Error setting groove: {str(e)}")
        return f"Error setting groove: {str(e)}"

@mcp.tool()
def continue_playing(ctx: Context) -> str:
    """Continue playback from the current position (unlike start_playback which plays from the insert marker)."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("continue_playing")
        return "Continued playback"
    except Exception as e:
        logger.error(f"Error continuing playback: {str(e)}")
        return f"Error continuing playback: {str(e)}"

@mcp.tool()
def set_session_record(ctx: Context, on: bool) -> str:
    """Enable or disable session recording.

    Parameters:
    - on: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_session_record", {"on": on})
        return f"{'Enabled' if on else 'Disabled'} session recording"
    except Exception as e:
        logger.error(f"Error setting session record: {str(e)}")
        return f"Error setting session record: {str(e)}"

@mcp.tool()
def set_session_automation_record(ctx: Context, on: bool) -> str:
    """Enable or disable session automation recording.

    Parameters:
    - on: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_session_automation_record", {"on": on})
        return f"{'Enabled' if on else 'Disabled'} session automation recording"
    except Exception as e:
        logger.error(f"Error setting session automation record: {str(e)}")
        return f"Error setting session automation record: {str(e)}"

@mcp.tool()
def re_enable_automation(ctx: Context) -> str:
    """Re-enable automation after manual parameter override."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("re_enable_automation")
        return "Re-enabled automation"
    except Exception as e:
        logger.error(f"Error re-enabling automation: {str(e)}")
        return f"Error re-enabling automation: {str(e)}"

@mcp.tool()
def set_punch_in(ctx: Context, on: bool) -> str:
    """Enable or disable punch-in recording.

    Parameters:
    - on: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_punch_in", {"on": on})
        return f"{'Enabled' if on else 'Disabled'} punch in"
    except Exception as e:
        logger.error(f"Error setting punch in: {str(e)}")
        return f"Error setting punch in: {str(e)}"

@mcp.tool()
def set_punch_out(ctx: Context, on: bool) -> str:
    """Enable or disable punch-out recording.

    Parameters:
    - on: True to enable, False to disable
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_punch_out", {"on": on})
        return f"{'Enabled' if on else 'Disabled'} punch out"
    except Exception as e:
        logger.error(f"Error setting punch out: {str(e)}")
        return f"Error setting punch out: {str(e)}"

@mcp.tool()
def set_scale(ctx: Context, name: str = None, root_note: int = None) -> str:
    """Set the global scale for the session.

    Parameters:
    - name: Scale name (e.g., "Major", "Minor", "Dorian", etc.)
    - root_note: Root note (0=C, 1=C#, 2=D, ..., 11=B)
    """
    try:
        ableton = get_ableton_connection()
        params = {}
        if name is not None:
            params["name"] = name
        if root_note is not None:
            params["root_note"] = root_note
        result = ableton.send_command("set_scale", params)
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error setting scale: {str(e)}")
        return f"Error setting scale: {str(e)}"

# ============ TRACK MANAGEMENT ============

@mcp.tool()
def create_return_track(ctx: Context) -> str:
    """Create a new return track."""
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("create_return_track")
        return f"Created return track '{result.get('name', '')}'. Total returns: {result.get('return_track_count', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating return track: {str(e)}")
        return f"Error creating return track: {str(e)}"

@mcp.tool()
def delete_return_track(ctx: Context, index: int) -> str:
    """Delete a return track.

    Parameters:
    - index: Index of the return track (0 = Return A, 1 = Return B, etc.)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("delete_return_track", {"index": index})
        return f"Deleted return track. Remaining: {result.get('return_track_count', 'unknown')}"
    except Exception as e:
        logger.error(f"Error deleting return track: {str(e)}")
        return f"Error deleting return track: {str(e)}"

@mcp.tool()
def set_track_color(ctx: Context, track_index: int, color_index: int) -> str:
    """Set the color of a track.

    Parameters:
    - track_index: The index of the track (0+ for regular, -1 for master, -2/-3 for returns)
    - color_index: Color index (0-69)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_color", {"track_index": track_index, "color_index": color_index})
        return f"Set track color to index {color_index}"
    except Exception as e:
        logger.error(f"Error setting track color: {str(e)}")
        return f"Error setting track color: {str(e)}"

@mcp.tool()
def set_track_monitoring(ctx: Context, track_index: int, state: int) -> str:
    """Set track monitoring state.

    Parameters:
    - track_index: The index of the track
    - state: 0=In, 1=Auto, 2=Off
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_monitoring", {"track_index": track_index, "state": state})
        states = {0: "In", 1: "Auto", 2: "Off"}
        return f"Set monitoring to {states.get(state, str(state))}"
    except Exception as e:
        logger.error(f"Error setting monitoring: {str(e)}")
        return f"Error setting monitoring: {str(e)}"

@mcp.tool()
def get_track_routing(ctx: Context, track_index: int) -> str:
    """Get input/output routing information for a track.

    Parameters:
    - track_index: The index of the track (0+ for regular, -1 for master, -2/-3 for returns)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_track_routing", {"track_index": track_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting routing: {str(e)}")
        return f"Error getting routing: {str(e)}"

@mcp.tool()
def set_track_input_routing(ctx: Context, track_index: int, routing_type_name: str) -> str:
    """Set the input routing of a track by name.

    Parameters:
    - track_index: The index of the track
    - routing_type_name: Name of the routing type (use get_track_routing to see available options)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_input_routing", {"track_index": track_index, "routing_type_name": routing_type_name})
        return f"Set input routing to '{routing_type_name}'"
    except Exception as e:
        logger.error(f"Error setting input routing: {str(e)}")
        return f"Error setting input routing: {str(e)}"

@mcp.tool()
def set_track_output_routing(ctx: Context, track_index: int, routing_type_name: str) -> str:
    """Set the output routing of a track by name.

    Parameters:
    - track_index: The index of the track
    - routing_type_name: Name of the routing type (use get_track_routing to see available options)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_track_output_routing", {"track_index": track_index, "routing_type_name": routing_type_name})
        return f"Set output routing to '{routing_type_name}'"
    except Exception as e:
        logger.error(f"Error setting output routing: {str(e)}")
        return f"Error setting output routing: {str(e)}"

@mcp.tool()
def fold_track(ctx: Context, track_index: int, fold: bool) -> str:
    """Fold or unfold a group track.

    Parameters:
    - track_index: The index of the group track
    - fold: True to fold (collapse), False to unfold (expand)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("fold_track", {"track_index": track_index, "fold": fold})
        return f"{'Folded' if fold else 'Unfolded'} track"
    except Exception as e:
        logger.error(f"Error folding track: {str(e)}")
        return f"Error folding track: {str(e)}"

# ============ SCENE MANAGEMENT ============

@mcp.tool()
def get_scene_info(ctx: Context, scene_index: int) -> str:
    """Get detailed information about a scene including color, tempo, and which clips are present.

    Parameters:
    - scene_index: The index of the scene
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_scene_info", {"scene_index": scene_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting scene info: {str(e)}")
        return f"Error getting scene info: {str(e)}"

@mcp.tool()
def set_scene_color(ctx: Context, scene_index: int, color_index: int) -> str:
    """Set the color of a scene.

    Parameters:
    - scene_index: The index of the scene
    - color_index: Color index (0-69)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_color", {"scene_index": scene_index, "color_index": color_index})
        return f"Set scene color to index {color_index}"
    except Exception as e:
        logger.error(f"Error setting scene color: {str(e)}")
        return f"Error setting scene color: {str(e)}"

@mcp.tool()
def set_scene_tempo(ctx: Context, scene_index: int, tempo: float) -> str:
    """Set the tempo for a specific scene (changes tempo when scene is launched).

    Parameters:
    - scene_index: The index of the scene
    - tempo: Tempo in BPM
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_scene_tempo", {"scene_index": scene_index, "tempo": tempo})
        return f"Set scene tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting scene tempo: {str(e)}")
        return f"Error setting scene tempo: {str(e)}"

@mcp.tool()
def duplicate_scene(ctx: Context, scene_index: int) -> str:
    """Duplicate a scene (copies all clips in the scene row).

    Parameters:
    - scene_index: The index of the scene to duplicate
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("duplicate_scene", {"scene_index": scene_index})
        return f"Duplicated scene. Total scenes: {result.get('scene_count', 'unknown')}"
    except Exception as e:
        logger.error(f"Error duplicating scene: {str(e)}")
        return f"Error duplicating scene: {str(e)}"

# ============ MIXER ============

@mcp.tool()
def set_crossfader(ctx: Context, position: float) -> str:
    """Set the crossfader position.

    Parameters:
    - position: Crossfader position (0.0 = full A, 0.5 = center, 1.0 = full B)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_crossfader", {"position": position})
        return f"Set crossfader to {position}"
    except Exception as e:
        logger.error(f"Error setting crossfader: {str(e)}")
        return f"Error setting crossfader: {str(e)}"

@mcp.tool()
def set_crossfade_assign(ctx: Context, track_index: int, assign: int) -> str:
    """Assign a track to a crossfader side.

    Parameters:
    - track_index: The index of the track
    - assign: 0=None, 1=A, 2=B
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_crossfade_assign", {"track_index": track_index, "assign": assign})
        assigns = {0: "None", 1: "A", 2: "B"}
        return f"Assigned track to crossfader {assigns.get(assign, str(assign))}"
    except Exception as e:
        logger.error(f"Error setting crossfade assign: {str(e)}")
        return f"Error setting crossfade assign: {str(e)}"

@mcp.tool()
def set_cue_volume(ctx: Context, volume: float) -> str:
    """Set the cue/preview volume.

    Parameters:
    - volume: Volume level (0.0 to 1.0 normalized)
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_cue_volume", {"volume": volume})
        return f"Set cue volume to {volume}"
    except Exception as e:
        logger.error(f"Error setting cue volume: {str(e)}")
        return f"Error setting cue volume: {str(e)}"

# ============ DEVICES ============

@mcp.tool()
def set_device_enabled(ctx: Context, track_index: int, device_index: int, enabled: bool) -> str:
    """Enable or disable (bypass) a device on a track.

    Parameters:
    - track_index: The index of the track (0+ for regular, -1 for master, -2/-3 for returns)
    - device_index: The index of the device
    - enabled: True to enable, False to disable/bypass
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("set_device_enabled", {"track_index": track_index, "device_index": device_index, "enabled": enabled})
        return f"{'Enabled' if enabled else 'Disabled'} {result.get('device_name', 'device')}"
    except Exception as e:
        logger.error(f"Error setting device enabled: {str(e)}")
        return f"Error setting device enabled: {str(e)}"

@mcp.tool()
def get_drum_pads(ctx: Context, track_index: int, device_index: int) -> str:
    """Get information about drum pads in a Drum Rack device.

    Parameters:
    - track_index: The index of the track containing the Drum Rack
    - device_index: The index of the Drum Rack device
    """
    try:
        ableton = get_ableton_connection()
        result = ableton.send_command("get_drum_pads", {"track_index": track_index, "device_index": device_index})
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting drum pads: {str(e)}")
        return f"Error getting drum pads: {str(e)}"

# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()
