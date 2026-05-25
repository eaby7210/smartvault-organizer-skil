#!/usr/bin/env bash
set -e

SKILL_NAME="smartvault-organizer"
SKILLS_DIR="${HOME}/.claude/skills/${SKILL_NAME}"

echo "Installing ${SKILL_NAME}..."

mkdir -p "${SKILLS_DIR}"
cp -r SKILL.md scripts .claude-plugin README.md .gitignore .mcp_state "${SKILLS_DIR}/"

echo "Installed to ${SKILLS_DIR}"
echo ""
echo "Done. Open Claude Code and run: /reload-plugins"
