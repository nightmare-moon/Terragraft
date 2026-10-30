# Foreground runner; leave this window open for dashboard plans and applies.
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.terragraft.local.json' -PathType Leaf)) { throw 'Missing configuration. Run INSTALL.ps1 first.' }
$config = Get-Content .terragraft.local.json -Raw | ConvertFrom-Json
Write-Host ('Terragraft runner root: ' + $config.projects_root) -ForegroundColor Cyan
python scripts/runner.py --root $config.projects_root --runner-id $config.runner_id --url $config.url
if ($LASTEXITCODE -ne 0) { throw 'Terragraft runner exited with an error' }
