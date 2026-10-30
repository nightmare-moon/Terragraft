# Run from the freshly extracted Terragraft source folder.
# Requires Git and GitHub CLI (`gh auth login`). Creates a NEW PRIVATE repo by default.
param(
  [string]$Repository = 'nightmare-moon/Terragraft',
  [ValidateSet('private','public')][string]$Visibility = 'private'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if ($Repository -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
  throw 'Repository must be in owner/name format, e.g. nightmare-moon/Terragraft'
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  throw 'Git was not found. Install Git for Windows first.'
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  throw 'GitHub CLI was not found. Install it with winget install --id GitHub.cli -e'
}
& gh auth status
if ($LASTEXITCODE -ne 0) { throw 'Run gh auth login first, then retry.' }

# Never publish from a folder with live credentials or Terraform state.
$danger = @('.env', '.terragraft.local.json', 'terraform.tfstate', 'terraform.tfstate.backup')
foreach ($file in $danger) {
  if (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file)) {
    throw "Local operational file '$file' exists. Publish from the clean GitHub-ready ZIP instead."
  }
}
$existingState = @(Get-ChildItem -LiteralPath $PSScriptRoot -File -Recurse -ErrorAction Stop | Where-Object {
  $_.Name -match '\.tfstate(\..*)?$|\.tfplan$|\.tfvars(\.json)?$|\.pem$|\.pfx$|\.p12$|\.key$'
})
if ($existingState.Count -gt 0) {
  throw 'Terraform state/plans, var files or key files were found. Publish from the clean extracted ZIP; do not upload operational data.'
}
if (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git')) {
  throw 'This folder is already a Git repository. Do not recreate/publish over its existing history.'
}
& gh repo view $Repository 1>$null 2>$null
if ($LASTEXITCODE -eq 0) {
  throw "Repository $Repository already exists. This helper is for a NEW repository; ask for an existing-repository publishing workflow."
}
Write-Host "Preparing a new $Visibility GitHub repository: $Repository" -ForegroundColor Cyan
& git init -b main
if ($LASTEXITCODE -ne 0) { throw 'git init failed' }
& git add -A
if ($LASTEXITCODE -ne 0) { throw 'git add failed' }
$staged = @(& git diff --cached --name-only)
$bad = @($staged | Where-Object { $_ -match '(^|/)(\.env(\..*)?|\.terragraft\.local\.json|.*\.tfstate(\..*)?|.*\.tfvars(\.json)?|.*\.tfplan)$' })
if ($bad.Count -gt 0) { throw 'Sensitive files staged: ' + ($bad -join ', ') }
& git commit -m 'Initial Terragraft v1.0 source'
if ($LASTEXITCODE -ne 0) { throw 'git commit failed. Check git config user.name and user.email.' }
& gh repo create $Repository "--$Visibility" --source . --remote origin --push
if ($LASTEXITCODE -ne 0) { throw 'GitHub repository creation/push failed. See the command output; local Git commit is intact.' }
Write-Host "Published: https://github.com/$Repository" -ForegroundColor Green
