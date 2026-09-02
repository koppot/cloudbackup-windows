# PowerShell Phase 1 VM Acceptance Test Runner for CloudBackup for Windows
# Executable on Windows 11 x64 clean test VM.

[CmdletBinding()]
param (
    [string]$SourceDir = "C:\CloudBackup-Acceptance-Test\source",
    [string]$RestoreDir = "C:\CloudBackup-Acceptance-Test\restore",
    [string]$ArtifactDir = "C:\CloudBackup-Acceptance-Test\artifacts"
)

$ErrorActionPreference = "Stop"

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host " CloudBackup for Windows — Phase 1 VM Acceptance Test Suite" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan

# 1. Ensure Directories
New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null
New-Item -ItemType Directory -Force -Path $RestoreDir | Out-Null
New-Item -ItemType Directory -Force -Path $ArtifactDir | Out-Null

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 2. Collect Preflight Evidence
Write-Host "`n[STEP 1] Collecting Pre-Install Environment Evidence..." -ForegroundColor Yellow
python "$ScriptDir\collect_evidence.py" --output "$ArtifactDir\pre_install_evidence.json"

# 3. Generate Synthetic Backup Dataset
Write-Host "`n[STEP 2] Generating Synthetic Test Dataset..." -ForegroundColor Yellow
python "$ScriptDir\generate_synthetic_data.py" --output-dir "$SourceDir" --manifest-out "$ArtifactDir\source_manifest.json"

# 4. Generate Cryptographic Source Manifest
Write-Host "`n[STEP 3] Generating Source Manifest..." -ForegroundColor Yellow
python "$ScriptDir\generate_manifest.py" --source-dir "$SourceDir" --output-base "$ArtifactDir\source_checksums"

# 5. Interactive Checkpoint: Installer Execution
Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host " INTERACTIVE CHECKPOINT: INSTALLER EXECUTION" -ForegroundColor Cyan
Write-Host " Execute 'CloudBackup-Setup.exe' now under administrator elevation." -ForegroundColor Cyan
Write-Host " Confirm installation to C:\Program Files\CloudBackup." -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Read-Host "Press ENTER after installation completes to continue"

# 6. Interactive Checkpoint: Standard User Runtime & OAuth Backup/Restore
Write-Host "`n================================================================================" -ForegroundColor Cyan
Write-Host " INTERACTIVE CHECKPOINT: OAUTH, BACKUP & RESTORE" -ForegroundColor Cyan
Write-Host " 1. Log in as a standard non-admin user." -ForegroundColor Cyan
Write-Host " 2. Launch CloudBackup from Start Menu (http://127.0.0.1:8765)." -ForegroundColor Cyan
Write-Host " 3. Complete OAuth with disposable Google test account." -ForegroundColor Cyan
Write-Host " 4. Add source directory: $SourceDir" -ForegroundColor Cyan
Write-Host " 5. Perform Dry Run and real Copy Backup." -ForegroundColor Cyan
Write-Host " 6. Perform Restore to: $RestoreDir" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Read-Host "Press ENTER after restore finishes to run SHA-256 Verification"

# 7. Collect Post-Install Evidence
Write-Host "`n[STEP 4] Collecting Post-Install Evidence..." -ForegroundColor Yellow
python "$ScriptDir\collect_evidence.py" --output "$ArtifactDir\post_install_evidence.json"

# 8. Verify Restore SHA-256 Checksums
Write-Host "`n[STEP 5] Verifying Restored Dataset Hashes..." -ForegroundColor Yellow
python "$ScriptDir\verify_restore.py" --source "$ArtifactDir\source_manifest.json" --restored-dir "$RestoreDir" --report-out "$ArtifactDir\restore_verification_report.json"

Write-Host "`n================================================================================" -ForegroundColor Green
Write-Host " [OK] VM Acceptance Script Finished. Inspect artifacts in: $ArtifactDir" -ForegroundColor Green
Write-Host "================================================================================" -ForegroundColor Green
