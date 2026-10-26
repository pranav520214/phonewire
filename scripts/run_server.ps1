# PhoneMic LAN Server Launcher for Windows
$ErrorActionPreference = "Stop"

Write-Host "Checking Python environment..." -ForegroundColor Cyan
$pythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pythonPath) {
    Write-Error "Python not found in PATH."
    exit 1
}

Write-Host "Starting PhoneMic LAN server via $pythonPath..." -ForegroundColor Green
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
& python "$repoRoot\scripts\run_server.py"
