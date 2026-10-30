# Register a brand-new Terraform stack (or a state-free stack with existing .tf files).
# Examples:
# .\CONNECT-PROJECT.ps1 -Path D:\TerraformProjects\Network -Workspace network-dev
# .\CONNECT-PROJECT.ps1 -Path D:\TerraformProjects\Demo -Workspace demo -Create
param(
  [Parameter(Mandatory=$true)][string]$Path,
  [Parameter(Mandatory=$true)][string]$Workspace,
  [string]$Name,
  [ValidateSet('terraform','tofu')][string]$Engine='terraform',
  [switch]$Create
)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path '.terragraft.local.json' -PathType Leaf)) { throw 'Run INSTALL.ps1 first.' }
$argsPython = @('scripts/connect_project.py','--path',$Path,'--workspace',$Workspace,'--engine',$Engine)
if ($Name) { $argsPython += @('--name',$Name) }
if ($Create) { $argsPython += '--create' }
& python @argsPython
if ($LASTEXITCODE -ne 0) { throw 'Project registration failed. No backend file was retained if registration failed.' }
