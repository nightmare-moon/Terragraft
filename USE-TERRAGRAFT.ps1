# Dot-source ONCE per PowerShell session to use manual Terraform CLI commands.
# Example: . "D:\Tools\Terragraft\USE-TERRAGRAFT.ps1"
$ErrorActionPreference='Stop'
$secretFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $secretFile -PathType Leaf)) { throw 'Missing .env; run INSTALL.ps1 first.' }
$values=@{}
Get-Content $secretFile | ForEach-Object {
  if ($_ -match '^([A-Z_]+)=(.*)$') { $values[$Matches[1]]=$Matches[2] }
}
$env:TF_HTTP_USERNAME='terraform'
$env:TF_HTTP_PASSWORD=$values['TERRAGRAFT_WRITER_TOKEN']
if (-not $env:TF_HTTP_PASSWORD) { throw 'Missing Terraform backend writer token.' }
Write-Host 'Terraform HTTP backend credentials loaded into this PowerShell session.' -ForegroundColor Green
