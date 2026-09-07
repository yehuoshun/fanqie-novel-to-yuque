#!/usr/bin/env node
// yuque_mcp_client.js - Direct MCP client for yuque
// Usage: node yuque_mcp_client.js <base64_payload>
const { spawn } = require('child_process');

const MCP_SERVER_CMD = 'node';
const MCP_SERVER_ARGS = [
    '/home/admin/.openclaw/workspace/skills/yuque-ai-mcp/server/dist/index.js',
    '--config', '/home/admin/.openclaw/workspace/skills/yuque-ai-mcp/config/config.json'
];

const b64Payload = process.argv[2];
const payload = JSON.parse(Buffer.from(b64Payload, 'base64').toString('utf8'));

// Build JSON-RPC request
const request = {
    jsonrpc: '2.0',
    id: 1,
    method: 'tools/call',
    params: {
        name: 'yuque_create_doc',
        arguments: payload
    }
};

const server = spawn(MCP_SERVER_CMD, MCP_SERVER_ARGS, {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env }
});

let output = '';
server.stdout.on('data', (data) => {
    output += data.toString();
});

server.stderr.on('data', (data) => {
    // Ignore stderr (logging)
});

server.on('close', (code) => {
    try {
        // Parse JSON-RPC response (may have multiple messages)
        const lines = output.trim().split('\n');
        for (const line of lines) {
            try {
                const msg = JSON.parse(line);
                if (msg.id === 1 && msg.result) {
                    const content = msg.result.content || [];
                    for (const c of content) {
                        if (c.text) {
                            // Try to parse as JSON
                            try {
                                const data = JSON.parse(c.text);
                                console.log(JSON.stringify(data));
                                process.exit(0);
                            } catch {
                                console.log(c.text);
                                process.exit(0);
                            }
                        }
                    }
                }
                if (msg.id === 1 && msg.error) {
                    console.error(JSON.stringify(msg.error));
                    process.exit(1);
                }
            } catch {
                // skip non-JSON lines
            }
        }
        console.log('RAW:', output);
        process.exit(0);
    } catch (e) {
        console.error('Error:', e.message);
        process.exit(1);
    }
});

server.on('error', (err) => {
    console.error('Spawn error:', err.message);
    process.exit(1);
});

// Send the request
server.stdin.write(JSON.stringify(request) + '\n');
server.stdin.end();