#!/bin/bash
# Shell wrapper for mcporter pipe
# Usage: ./yuque_pipe.sh <json_file>
JSON_FILE="$1"
cat "$JSON_FILE" | mcporter call "yuque-mcp.yuque_create_doc" --args - --output json 2>&1