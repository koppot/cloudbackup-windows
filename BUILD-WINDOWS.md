# CloudBackup for Windows — Build & Packaging Guide

This document describes how maintainers build the standalone PyInstaller executable, Inno Setup installer, and execute supplementary platform-neutral Docker regression tests.

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
Expected output: `CloudBackup for Windows v1.0.0-phase1 (x64 Phase 1 Development Preview)`

### 4. Build Inno Setup Installer
```cmd
iscc installer/CloudBackupInstaller.iss
```
This generates `dist/CloudBackup-Setup.exe`.

---

## Supplementary Platform-Neutral Docker Testing

> [!NOTE]
> **LABEL: SUPPLEMENTARY PLATFORM-NEUTRAL VALIDATION ONLY**  
> Docker validation runs hermetic platform-neutral tests and repository pattern scanning on Linux. Image construction fetches pinned dependencies from PyPI (`requirements-test.txt`), while container **runtime execution** is strictly network-isolated with `--network none`.
> Docker does **NOT** validate Windows installer compilation, UAC elevation, `ProgramData` ACLs, Task Scheduler, or Windows security controls.

### Build & Execute Hardened Docker Test Target
```bash
docker build -f Dockerfile.test -t cloudbackup-test .
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --tmpfs /tmp:exec,mode=1777 \
  cloudbackup-test
```
