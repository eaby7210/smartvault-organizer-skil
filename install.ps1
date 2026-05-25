$ErrorActionPreference = "Stop"

$PluginName  = "smartvault-organizer"
$Marketplace = "smartvault-organizer-marketplace"
$Version     = "1.0.0"
$ClaudeDir   = Join-Path $env:USERPROFILE ".claude"
$CacheDir    = Join-Path $ClaudeDir "plugins\cache\$Marketplace\$PluginName\$Version"
$Settings    = Join-Path $ClaudeDir "settings.json"

Write-Host "Installing $PluginName..."

# Copy plugin files to cache
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
Copy-Item -Recurse -Force SKILL.md, scripts, .claude-plugin, .mcp_state, README.md, .gitignore $CacheDir

# Patch settings.json
$settingsObj = if (Test-Path $Settings) {
    Get-Content $Settings -Raw | ConvertFrom-Json
} else {
    [PSCustomObject]@{}
}

if (-not $settingsObj.PSObject.Properties["enabledPlugins"]) {
    $settingsObj | Add-Member -NotePropertyName "enabledPlugins" -NotePropertyValue ([PSCustomObject]@{})
}
$settingsObj.enabledPlugins | Add-Member -NotePropertyName "$PluginName@$Marketplace" -NotePropertyValue $true -Force

if (-not $settingsObj.PSObject.Properties["extraKnownMarketplaces"]) {
    $settingsObj | Add-Member -NotePropertyName "extraKnownMarketplaces" -NotePropertyValue ([PSCustomObject]@{})
}
$localSource = [PSCustomObject]@{ source = "local"; path = $CacheDir }
$settingsObj.extraKnownMarketplaces | Add-Member -NotePropertyName $Marketplace -NotePropertyValue ([PSCustomObject]@{ source = $localSource }) -Force

$settingsObj | ConvertTo-Json -Depth 10 | Set-Content $Settings
Write-Host "Settings updated."

Write-Host ""
Write-Host "Done. Open Claude Code and run: /reload-plugins"
