$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
python -m PyInstaller --noconfirm --clean packaging\study_tracker.spec
Write-Host "Built dist\StudyTracker\StudyTracker.exe"
