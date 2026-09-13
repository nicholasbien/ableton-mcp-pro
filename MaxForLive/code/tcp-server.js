// tcp-server.js — Node.js TCP server for Max for Live AbletonMCP device
// Communicates with lom-handler.js by passing JSON strings as Max messages

var maxAPI = require("max-api");
var net = require("net");

// Port comes from the node.script box arguments ("node.script tcp-server.js 9878").
// Default 9878 so the device can run alongside the Python Remote Script on 9877.
var PORT = parseInt(process.argv[2], 10) || 9878;
var server = null;
var pendingRequests = {}; // requestId -> socket
var nextRequestId = 1;

// Start TCP server
function startServer() {
    server = net.createServer(function (socket) {
        maxAPI.post("AbletonMCP: Client connected from " + socket.remoteAddress);

        var buffer = "";

        socket.on("data", function (data) {
            buffer += data.toString("utf-8");

            var parsed = tryParseJSON(buffer);
            while (parsed) {
                var command = parsed.value;
                buffer = parsed.remaining;

                var requestId = String(nextRequestId++);
                pendingRequests[requestId] = socket;

                // Send command as: command <requestId> <jsonString>
                var jsonStr = JSON.stringify({
                    type: command.type || "",
                    params: command.params || {}
                });
                maxAPI.outlet("command", requestId, jsonStr);

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
            maxAPI.post("AbletonMCP: Port " + PORT + " already in use. Another copy of this device, or the Remote Script on the same port?");
        } else {
            maxAPI.post("AbletonMCP: Server error: " + err.message);
        }
    });

    server.listen(PORT, "127.0.0.1", function () {
        maxAPI.post("AbletonMCP: Listening on port " + PORT);
    });
}

// Handle response from lom-handler: "response <requestId> <jsonString>"
maxAPI.addHandler("response", function () {
    // arguments come as: requestId, jsonString
    var args = Array.prototype.slice.call(arguments);
    var requestId = String(args[0]);
    var jsonStr = args.slice(1).join(" ");

    var socket = pendingRequests[requestId];
    if (socket && !socket.destroyed) {
        try {
            socket.write(jsonStr);
        } catch (err) {
            maxAPI.post("Error sending response: " + err.message);
        }
    }
    delete pendingRequests[requestId];
});

// Ignore bangs
maxAPI.addHandler(maxAPI.MESSAGE_TYPES.BANG, function () {});

// Ignore other messages
maxAPI.addHandler(maxAPI.MESSAGE_TYPES.ALL, function () {});

function cleanupSocket(socket) {
    var keys = Object.keys(pendingRequests);
    for (var i = 0; i < keys.length; i++) {
        if (pendingRequests[keys[i]] === socket) {
            delete pendingRequests[keys[i]];
        }
    }
}

function tryParseJSON(str) {
    str = str.trimLeft();
    if (!str || str[0] !== "{") return null;

    var depth = 0;
    var inString = false;
    var escape = false;

    for (var i = 0; i < str.length; i++) {
        var ch = str[i];
        if (escape) { escape = false; continue; }
        if (ch === "\\") { escape = true; continue; }
        if (ch === '"') { inString = !inString; continue; }
        if (inString) continue;
        if (ch === "{") depth++;
        else if (ch === "}") {
            depth--;
            if (depth === 0) {
                var jsonStr = str.substring(0, i + 1);
                try {
                    var value = JSON.parse(jsonStr);
                    return { value: value, remaining: str.substring(i + 1) };
                } catch (e) { return null; }
            }
        }
    }
    return null;
}

maxAPI.addHandler("shutdown", function () {
    if (server) { server.close(); maxAPI.post("AbletonMCP: Server stopped"); }
});

startServer();
