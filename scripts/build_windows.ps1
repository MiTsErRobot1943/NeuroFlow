$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

python -m PyInstaller `
  --noconfirm `
  --clean `
  --name NeuroFlowDesktop `
  --onedir `
  --add-data "Template;Template" `
  --add-data "schema.sql;." `
  run_desktop.py

Write-Host "Build complete. Output: $projectRoot\dist\NeuroFlowDesktop" -ForegroundColor Green

