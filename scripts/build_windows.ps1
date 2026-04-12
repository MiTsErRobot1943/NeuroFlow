$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

New-Item -ItemType Directory -Force -Path "$projectRoot\dist" | Out-Null
New-Item -ItemType Directory -Force -Path "$projectRoot\build" | Out-Null

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name NeuroFlowDesktop `
  --onedir `
  --collect-submodules webview `
  --collect-data webview `
  --add-data "src/assets/templates;src/assets/templates" `
  --add-data "src/assets/schema.sql;src/assets" `
  --distpath "$projectRoot\dist" `
  --workpath "$projectRoot\build" `
  scripts/runtime/run_desktop.py

Write-Host "Build complete. Output: $projectRoot\dist\NeuroFlowDesktop" -ForegroundColor Green

