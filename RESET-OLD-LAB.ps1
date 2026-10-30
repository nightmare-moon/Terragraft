# Optional cleanup of the ORIGINAL terragraft-lab Docker project only.
# Not required for new installs unless its old API still occupies port 8080.
param([switch]$DeleteOldData)
$ErrorActionPreference='Stop'
Write-Host 'Stopping only the OLD terragraft-lab Compose stack (not this new terragraft stack).'
docker compose -p terragraft-lab down --remove-orphans
if ($LASTEXITCODE -ne 0) { throw 'Old Docker stack stop failed.' }
if ($DeleteOldData) {
  Write-Host 'CAUTION: This will PERMANENTLY erase old Terraform state in volume terragraft-lab_pg_data.' -ForegroundColor Red
  $confirm = Read-Host 'Type DELETE-OLD-STATE to permanently delete the old volume'
  if ($confirm -ne 'DELETE-OLD-STATE') { throw 'Canceled volume deletion. Old state was preserved.' }
  docker volume rm terragraft-lab_pg_data
  if ($LASTEXITCODE -ne 0) { throw 'Docker volume removal failed. Check whether any container still uses the volume.' }
}
Write-Host 'Old lab cleanup finished. The new Terragraft database remains separate.'
