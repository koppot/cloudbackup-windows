# Release Notes — Phase 1: Windows Portability & Nontechnical Installer

**Version**: `v1.0.0-phase1`
**Target Platform**: Windows 10 / 11 x64

---

## Executive Summary

Phase 1 establishes true Windows portability, fail-closed security, standalone executable packaging, a nontechnical setup wizard (`CloudBackup-Setup.exe`), and an automated CI/CD pipeline.

---

## Key Highlights

### 1. Windows Portability & Central Path Management
- Replaced Unix path assumptions with `pathlib.Path` abstractions.
- Centralized runtime directory management in `shared/paths.py`:
  - Binaries: `C:\Program Files\CloudBackup`
  - Data Root: `C:\ProgramData\CloudBackup` (`config`, `state`, `logs`, `temp`)
  - Preferences: `%LocalAppData%\CloudBackup`
- Enforced strict path normalization and path safety validation (`validate_local_path()`), preventing directory traversal, NUL byte injection, and Windows reserved name conflicts.

### 2. Fail-Closed Rclone Discovery & Subprocess Security
- Implemented `resolve_rclone_binary()` with SHA-256 manifest verification against `shared/rclone_manifest.json`.
- Disabled implicit `PATH` / `shutil.which()` lookups to prevent binary hijacking.
- Added `run_safe_subprocess()` helper with mandatory argument arrays (`shell=False`), timeout management, and automatic redaction of passphrases, OAuth tokens, and secrets in logs.

### 3. Nontechnical Setup Wizard & Executable Packaging
- Built standalone PyInstaller x64 distribution (`CloudBackup.spec`) outputting to `dist/CloudBackup/`.
- Created Inno Setup GUI installer `CloudBackup-Setup.exe` with desktop/start menu shortcuts, uninstaller, and least-privilege ACLs.
- Runtime execution requires **NO administrative rights**.

### 4. Automated CI/CD Pipeline
- Added GitHub Actions workflow (`.github/workflows/ci.yml`) running on `windows-latest` for unit testing, PyInstaller packaging, Inno Setup compilation, and artifact generation.

---

## Retained Safety Guarantees

- Default backup mode remains non-destructive `copy` mode.
- Remote backup data is **never** deleted by uninstallation or task changes.
- Credential handling and encryption passphrases remain zero-knowledge and redacted.
