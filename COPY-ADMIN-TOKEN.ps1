# Copies the local dashboard admin token to clipboard only on deliberate invocation.
$ErrorActionPreference='Stop'
$envFile=Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile -PathType Leaf)) { throw 'Not installed. Run INSTALL.ps1 first.' }
$line=Get-Content $envFile | Where-Object { $_ -match '^TERRAGRAFT_ADMIN_TOKEN=' } | Select-Object -First 1
if (-not $line) { throw 'Admin token not found.' }
$token=$line.Split('=',2)[1]
Set-Clipboard -Value $token
Write-Host 'Admin token copied to clipboard. Paste it into the Console token field and click Connect.' -ForegroundColor Green
Write-Host 'The clipboard contains a SECRET; clear it after use if others can access this computer.' -ForegroundColor Yellow
