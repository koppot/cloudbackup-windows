# CloudBackup for Windows — Release Process

This document outlines the step-by-step process for publishing official CloudBackup releases.

---

## Release Policy & Gating Criteria

> [!IMPORTANT]
> **STABLE RELEASE BLOCKER**: No stable release tag (`v*`) or GitHub Release asset publication is permitted until **ALL 15 STEPS** in `docs/WINDOWS-MANUAL-QA.md` pass cleanly on a clean Windows 11 x64 virtual machine, producing **ZERO SHA-256 file checksum mismatches** on restore.

---

## Step-by-Step Release Workflow

### 1. Code Quality & Pre-flight
- [ ] Ensure all unit tests pass locally: `python -m pytest -v`
- [ ] Verify `shared/rclone_manifest.json` contains current pinned rclone version and SHA-256 hash.
- [ ] Confirm no secrets, credentials, or `.env` files are tracked in git via `git status` and manual review.

### 2. Version Bump
- Update version string in:
  - `shared/version.py` (if present) or `windows/cli.py`
  - `installer/CloudBackupInstaller.iss` (`#define MyAppVersion "1.0.0"`)
  - `RELEASE_NOTES.md`

### 3. Tagging & GitHub Actions Build
Create and push a signed git release tag:
```bash
git tag -a v1.0.0 -m "Release v1.0.0 — Phase 1 Windows Portability & Installer"
git push origin v1.0.0
```

### 4. CI Artifact Verification
GitHub Actions will automatically run `.github/workflows/ci.yml`:
1. Runs full unit test matrix on `windows-latest` (Python 3.10, 3.11, 3.12).
2. Stages and hash-verifies pinned `rclone.exe` binary.
3. Builds standalone PyInstaller distribution (`dist/CloudBackup/`).
4. Runs frozen executable smoke test.
5. Compiles Inno Setup installer (`CloudBackup-Setup.exe`).
6. Generates `checksums.sha256` manifest.
7. Uploads release assets to GitHub Release draft.

### 5. Manual QA & Release Publication
1. Download `CloudBackup-Setup.exe` from the draft release.
2. Follow `docs/WINDOWS-MANUAL-QA.md` on a clean Windows 11 x64 VM.
3. Complete disposable-cloud backup and restore verification; confirm **0 SHA-256 mismatches**.
4. Once all 15 gates pass cleanly, publish the GitHub release.
