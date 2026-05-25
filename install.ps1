$ErrorActionPreference = "Stop"

$SkillName = "smartvault-organizer"
$SkillsDir = Join-Path $env:USERPROFILE ".claude\skills\$SkillName"

Write-Host "Installing $SkillName..."

New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
Copy-Item -Recurse -Force SKILL.md, scripts, .claude-plugin, README.md, .gitignore, .mcp_state $SkillsDir

Write-Host "Installed to $SkillsDir"
Write-Host ""
Write-Host "Done. Open Claude Code and run: /reload-plugins"
