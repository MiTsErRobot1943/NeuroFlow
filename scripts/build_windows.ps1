[CmdletBinding()]
param(
  [switch]$IncludeOllama
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

New-Item -ItemType Directory -Force -Path "$projectRoot\dist" | Out-Null
New-Item -ItemType Directory -Force -Path "$projectRoot\build" | Out-Null

$pyInstallerArgs = @(
  "--noconfirm",
  "--clean",
  "--name", "NeuroFlowDesktop",
  "--onedir",
  "--collect-submodules", "webview",
  "--collect-data", "webview",
  "--add-data", "src/assets/templates;src/assets/templates",
  "--add-data", "src/assets/schema.sql;src/assets",
  "--distpath", "$projectRoot\dist",
  "--workpath", "$projectRoot\build"
)

if (-not $IncludeOllama) {
  # Keep Ollama optional for desktop packaging; app falls back when the module is absent.
  $pyInstallerArgs += @("--exclude-module", "ollama", "--exclude-module", "langchain_ollama")
}

python -m PyInstaller @pyInstallerArgs scripts/runtime/run_desktop.py

if ($IncludeOllama) {
  Write-Host "Build complete with Ollama client bundled. Output: $projectRoot\dist\NeuroFlowDesktop" -ForegroundColor Green
} else {
  Write-Host "Build complete without Ollama client (optional). Output: $projectRoot\dist\NeuroFlowDesktop" -ForegroundColor Green
}

Write-Host "Note: packaged desktop startup runs a local-AI hardware preflight (CPU/RAM/disk) and logs guidance if specs are below recommendation." -ForegroundColor Yellow

