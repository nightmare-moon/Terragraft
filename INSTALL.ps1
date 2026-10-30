# One-time, standalone Windows installation. No upgrades or state migration.
param(
  [string]$ProjectsRoot = $(if (Test-Path 'D:\') { 'D:\TerraformProjects' } else { Join-Path $HOME 'TerraformProjects' }),
  [switch]$NoBrowser,
  [switch]$NoRunner
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
Write-Host 'Terragraft - Fresh Windows installation' -ForegroundColor Cyan
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3 is not on PATH. Install Python 3 and reopen PowerShell.' }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw 'Docker Desktop is not installed or Docker is not on PATH.' }
docker info --format '{{.ServerVersion}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop engine is not running. Start Docker Desktop first.' }
if (-not (Get-Command terraform -ErrorAction SilentlyContinue) -and -not (Get-Command tofu -ErrorAction SilentlyContinue)) {
  Write-Warning 'Neither terraform nor tofu is on PATH. Server can start, but plans/applies require one CLI installed on Windows.'
}
if (Test-Path '.env' -PathType Leaf) {
  throw 'An installation already exists in this folder. Run RUN.ps1 rather than reinitializing secrets.'
}
python scripts/setup_local.py --projects-root $ProjectsRoot
if ($LASTEXITCODE -ne 0) { throw 'Local installation configuration failed' }
Write-Host 'Starting containers and Windows runner...' -ForegroundColor Cyan
& (Join-Path $PSScriptRoot 'RUN.ps1') -NoBrowser:$NoBrowser -NoRunner:$NoRunner
