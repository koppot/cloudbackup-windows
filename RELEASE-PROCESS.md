# CloudBackup for Windows — Release Process

This document outlines the step-by-step process for publishing official Phase 1 releases.

---

## Release Checklist

### 1. Code Quality & Pre-flight
- [ ] Ensure all unit tests pass locally: `python -m pytest -v`
- [ ] Verify `shared/rclone_manifest.json` contains current pinned version and SHA-256 hash.
- [ ] Confirm no secrets, credentials, or `.env` files are tracked in git.

### 2. Version Bump
- Update version string in:
  - `shared/version.py` (if present) or `windows/cli.py`
  - `installer/CloudBackupInstaller.iss` (`#define MyAppVersion "1.0.0"`)
  - `RELEASE_NOTES.md`

### 3. Tagging & GitHub Actions
Create and push a signed git release tag:
```bash
git tag -a v1.0.0 -m "Release v1.0.0 — Phase 1 Windows Portability & Installer"
git push origin v1.0.0
```

### 4. CI Artifact Verification
GitHub Actions will automatically run `.github/workflows/ci.yml`:
1. Runs full unit test suite on `windows-latest`.
2. Builds PyInstaller package (`dist/CloudBackup/`).
3. Compiles Inno Setup installer (`CloudBackup-Setup.exe`).
4. Generates `checksums.sha256`.
5. Uploads release assets to GitHub Release draft.

### 5. Manual QA & Release Publication
1. Download `CloudBackup-Setup.exe` from the draft release.
2. Follow `docs/WINDOWS-MANUAL-QA.md` on a clean Windows 11 machine.
3. Once QA checks pass, publish the GitHub release.
