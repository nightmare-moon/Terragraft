# Check the fresh Terragraft server and runner prerequisites.
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
Write-Host 'Docker services:' -ForegroundColor Cyan
docker compose -p terragraft ps
Write-Host 'Terragraft health:' -ForegroundColor Cyan
Invoke-RestMethod 'http://127.0.0.1:8080/health' | Format-List
Write-Host 'Terraform/OpenTofu CLI:' -ForegroundColor Cyan
if (Get-Command terraform -ErrorAction SilentlyContinue) { terraform version }
elseif (Get-Command tofu -ErrorAction SilentlyContinue) { tofu version }
else { Write-Warning 'Terraform or OpenTofu CLI must be installed for plan/apply.' }
Write-Host 'Configured projects root:' -ForegroundColor Cyan
if (Test-Path '.terragraft.local.json') {
  $c=Get-Content .terragraft.local.json -Raw | ConvertFrom-Json
  Write-Host $c.projects_root
}
