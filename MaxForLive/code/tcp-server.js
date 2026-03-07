// tcp-server.js — Node.js TCP server for Max for Live AbletonMCP device
// Runs inside node.script, communicates with lom-handler.js via Max dicts

var maxAPI = require("max-api");
var net = require("net");

var PORT = 9877;
var server = null;
var pendingRequests = {}; // requestId -> { socket, buffer }
var nextRequestId = 1;

// Start TCP server
function startServer() {
    server = net.createServer(function (socket) {
        maxAPI.post("AbletonMCP: Client connected from " + socket.remoteAddress);

        var buffer = "";

        socket.on("data", function (data) {
            buffer += data.toString("utf-8");

            // Try to parse complete JSON from buffer
            var parsed = tryParseJSON(buffer);
            while (parsed) {
                var command = parsed.value;
                buffer = parsed.remaining;

                var requestId = String(nextRequestId++);
                pendingRequests[requestId] = socket;

                // Write command to request dict and trigger lom-handler
                maxAPI.setDict("request_dict", {
                    requestId: requestId,
                    type: command.type || "",
                    params: command.params || {}
                }).then(function () {
                    maxAPI.outlet("command", requestId);
                }).catch(function (err) {
                    maxAPI.post("Error setting request dict: " + err);
                    sendResponse(requestId, { status: "error", message: "Internal error: " + err });
                });

                parsed = tryParseJSON(buffer);
            }
        });

        socket.on("error", function (err) {
            maxAPI.post("AbletonMCP: Socket error: " + err.message);
            cleanupSocket(socket);
        });

        socket.on("close", function () {
            maxAPI.post("AbletonMCP: Client disconnected");
            cleanupSocket(socket);
        });
    });

    server.on("error", function (err) {
        if (err.code === "EADDRINUSE") {
            maxAPI.post("AbletonMCP: Port " + PORT + " already in use. Is the Remote Script running?");
        } else {
            maxAPI.post("AbletonMCP: Server error: " + err.message);
        }
    });

    server.listen(PORT, "127.0.0.1", function () {
        maxAPI.post("AbletonMCP: Listening on port " + PORT);
    });
}

// Handle response from lom-handler
maxAPI.addHandler("response", function () {
    maxAPI.getDict("response_dict").then(function (dict) {
        var requestId = dict.requestId;
        sendResponse(requestId, {
            status: dict.status || "success",
            result: dict.result,
            message: dict.message
        });
    }).catch(function (err) {
        maxAPI.post("Error reading response dict: " + err);
    });
});

function sendResponse(requestId, response) {
    var socket = pendingRequests[requestId];
    if (socket && !socket.destroyed) {
        try {
            // Clean up response — remove undefined fields
            var clean = { status: response.status };
            if (response.result !== undefined) clean.result = response.result;
            if (response.message !== undefined) clean.message = response.message;
            socket.write(JSON.stringify(clean));
        } catch (err) {
            maxAPI.post("Error sending response: " + err.message);
        }
    }
    delete pendingRequests[requestId];
}

function cleanupSocket(socket) {
    var keys = Object.keys(pendingRequests);
    for (var i = 0; i < keys.length; i++) {
        if (pendingRequests[keys[i]] === socket) {
            delete pendingRequests[keys[i]];
        }
    }
}

// Try to parse a complete JSON object from the front of a string buffer.
// Returns { value, remaining } on success, or null if incomplete.
function tryParseJSON(str) {
    str = str.trimLeft();
    if (!str || str[0] !== "{") return null;

    var depth = 0;
    var inString = false;
    var escape = false;

    for (var i = 0; i < str.length; i++) {
        var ch = str[i];
        if (escape) {
            escape = false;
            continue;
        }
        if (ch === "\\") {
            escape = true;
            continue;
        }
        if (ch === '"') {
            inString = !inString;
            continue;
        }
        if (inString) continue;
        if (ch === "{") depth++;
        else if (ch === "}") {
            depth--;
            if (depth === 0) {
                var jsonStr = str.substring(0, i + 1);
                try {
                    var value = JSON.parse(jsonStr);
                    return { value: value, remaining: str.substring(i + 1) };
                } catch (e) {
                    return null;
                }
            }
        }
    }
    return null;
}

// Clean shutdown
maxAPI.addHandler("shutdown", function () {
    if (server) {
        server.close();
        maxAPI.post("AbletonMCP: Server stopped");
    }
});

startServer();
