# Stop central Docker services. Stop the Windows runner window manually with Ctrl+C.
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
docker compose -p terragraft down
if ($LASTEXITCODE -ne 0) { throw 'Could not stop Terragraft Docker services.' }
Write-Host 'Terragraft containers stopped. Database volume and .env were preserved.'
