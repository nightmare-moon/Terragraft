# Start an existing one-time installation, then optionally launch the Windows runner.
param([switch]$NoBrowser,[switch]$NoRunner)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.env' -PathType Leaf)) { throw 'Not installed yet. Run INSTALL.ps1 first.' }
if (-not (Test-Path '.terragraft.local.json' -PathType Leaf)) { throw 'Missing local runner configuration. Do not regenerate .env; restore the original config.' }
docker compose -p terragraft up --build -d
if ($LASTEXITCODE -ne 0) {
  Write-Host 'If port 8080 is occupied by the old lab, run RESET-OLD-LAB.ps1 then retry RUN.ps1.' -ForegroundColor Yellow
  throw 'Docker Compose startup failed.'
}
$ready=$false
for ($i=0; $i -lt 30; $i++) {
  try {
    $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8080/health' -TimeoutSec 3
    if ($health.status -eq 'ok' -and $health.version -eq '1.0.0') { $ready=$true;break }
  } catch { }
  Start-Sleep -Seconds 1
}
if (-not $ready) {
  docker compose -p terragraft logs --tail=80 api
  throw 'Terragraft API failed its health check (expected version 1.0.0). See Docker logs above.'
}
Write-Host 'Terragraft v1.0.0 is online: http://127.0.0.1:8080/console' -ForegroundColor Green
Write-Host 'Run CONNECT-PROJECT.ps1 for each new Terraform project (server installs only once).'
if (-not $NoRunner) {
  $script = Join-Path $PSScriptRoot 'RUNNER.ps1'
  Start-Process -FilePath 'powershell.exe' -ArgumentList "-NoExit -NoProfile -ExecutionPolicy Bypass -File `"$script`""
  Write-Host 'Opened Windows runner in a separate PowerShell window. Leave it running for dashboard jobs.'
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8080/console' }
