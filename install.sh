#!/usr/bin/env bash
set -e

PLUGIN_NAME="smartvault-organizer"
MARKETPLACE="smartvault-organizer-marketplace"
VERSION="1.0.0"
CLAUDE_DIR="${HOME}/.claude"
CACHE_DIR="${CLAUDE_DIR}/plugins/cache/${MARKETPLACE}/${PLUGIN_NAME}/${VERSION}"
SETTINGS="${CLAUDE_DIR}/settings.json"

echo "Installing ${PLUGIN_NAME}..."

# Copy plugin files to cache
mkdir -p "${CACHE_DIR}"
cp -r SKILL.md scripts .claude-plugin .mcp_state README.md .gitignore "${CACHE_DIR}/"

# Patch settings.json
python3 - <<PYEOF
import json, os

settings_path = "${SETTINGS}"
os.makedirs(os.path.dirname(settings_path), exist_ok=True)

try:
    with open(settings_path) as f:
        settings = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    settings = {}

plugin_key = "${PLUGIN_NAME}@${MARKETPLACE}"
settings.setdefault("enabledPlugins", {})[plugin_key] = True
settings.setdefault("extraKnownMarketplaces", {})["${MARKETPLACE}"] = {
    "source": {"source": "local", "path": "${CACHE_DIR}"}
}

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print("Settings updated.")
PYEOF

echo ""
echo "Done. Open Claude Code and run: /reload-plugins"
