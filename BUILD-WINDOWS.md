# CloudBackup for Windows — Build & Packaging Guide

This document describes how maintainers build the standalone PyInstaller executable and Inno Setup installer.

---

## Prerequisites

- **OS**: Windows 10/11 x64 (or GitHub Actions `windows-latest` runner).
- **Python**: Python 3.10+ x64.
- **Inno Setup**: Inno Setup 6.x (installed via `choco install innosetup -y`).
- **Dependencies**: `pip install -r requirements.txt pyinstaller pytest`

---

## Build Steps

### 1. Run Unit Tests
```cmd
python -m pytest -v
```

### 2. Build PyInstaller Executable Distribution
```cmd
pyinstaller --noconfirm CloudBackup.spec
```
This produces `dist/CloudBackup/CloudBackup.exe` containing all bundled static assets, templates, schemas, and dependencies.

### 3. Verify Frozen Executable
```cmd
.\dist\CloudBackup\CloudBackup.exe --version
```
Expected output: `CloudBackup for Windows v1.0.0 (x64)`

### 4. Build Inno Setup Installer
```cmd
iscc installer/CloudBackupInstaller.iss
```
This generates `dist/CloudBackup-Setup.exe`.

### 5. Generate SHA-256 Checksums
```powershell
Get-FileHash -Algorithm SHA256 dist\CloudBackup-Setup.exe | Format-List
```
