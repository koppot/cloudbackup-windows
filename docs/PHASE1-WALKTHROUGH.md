# Phase 1 Implementation Walkthrough — Windows Portability & Nontechnical Installer (Phase 1 Development Preview)

All implementation and remediation tasks for **Phase 1: Windows Portability and Nontechnical Installer** have been completed on branch `feature/windows-portability-installer`.

---

## 1. Summary of Remediated Changes

### Hardcoded Credentials Removal
- Completely removed all hardcoded crypt passphrases (`SuperMicroBackup2026!Secure`) from `windows/engine.py`.
- `setup_wizard` and `_register_new_gdrive` now dynamically generate passphrases using `secrets.token_urlsafe(32)` or accept user-configured secrets.

### Fail-Closed Rclone Trust Policy (`shared/rclone.py` & `shared/rclone_manifest.json`)
- Missing manifest (`shared/rclone_manifest.json`), malformed manifest, missing bundle executable, or SHA-256 hash mismatch halts rclone execution immediately.
- Default resolution requires verified bundled binary. External overrides are permitted ONLY via explicit absolute paths (`os.path.isabs`). Prohibited bare `PATH` lookups.

### Environment & Security Sanitization (`shared/subprocess_utils.py`)
- Stripped inherited `RCLONE_CONFIG` and `RCLONE_CONF` environment variables in process execution to prevent credential leakage.
- Enforced argument lists without `shell=True` across all subprocess calls.
- Enforced loopback-only host binding (`127.0.0.1` / `localhost`) in `windows/cli.py` and `windows/web_server.py`. Non-loopback bind hosts are explicitly rejected.

### Least-Privilege Directory Permissions (`installer/CloudBackupInstaller.iss`)
- Replaced broad `authusers-modify` permissions on `ProgramData\CloudBackup` subdirectories with least-privilege `system-full admins-full` access.

### Source Selection Directory Validation (`windows/web_server.py` & `shared/paths.py`)
- Validated that added source paths exist (`must_exist=True`), are directories (`is_dir()`), and are accessible before adding to job sources.

### Task Scheduler Management (`windows/engine.py`)
- Scheduled tasks are NOT registered during installer setup. Added safe, idempotent `schtasks.exe` creation, enablement, and disablement helpers (`create_scheduled_task`, `enable_scheduler`, `disable_scheduler`).

### CI/CD Pipeline & Pinned Rclone Staging (`.github/workflows/ci.yml`)
- Added workflow concurrency (`cancel-in-progress: true`) to prevent redundant CI builds.
- Split jobs into `test-windows` (unit test matrix across Python 3.10, 3.11, 3.12), `package-installer-windows` (executable build & Inno Setup compilation), and `unit-tests-linux`.
- Added CI staging step on `windows-latest` to download pinned rclone x64 (`v1.68.2`), verify SHA-256 hash against `shared/rclone_manifest.json`, and fail closed before PyInstaller packaging.
- Added draft release automation step (`softprops/action-gh-release@v2`) for version tags (`v*`).

### Integration & Unit Test Suite (`tests/test_frozen_integration.py` & others)
- Created `tests/test_frozen_integration.py` verifying resource discovery, schema loading, static asset presence, single-instance locking, and loopback web server security rejection.
- All 85 unit tests pass cleanly.

---

## 2. Verification & Test Results

### Unit & Integration Test Suite
Ran `.venv/bin/python -m unittest discover tests`:
```text
Ran 85 tests in 0.139s
OK (85 passed, 0 failures)
```

### PyInstaller Standalone Executable Test
Ran `.venv/bin/pyinstaller --noconfirm CloudBackup.spec`:
```text
Building COLLECT COLLECT-00.toc completed successfully.
Build complete! The results are available in: dist/CloudBackup
```
Ran `dist/CloudBackup/CloudBackup --version`:
```text
CloudBackup for Windows v1.0.0-phase1 (x64 Phase 1 Development Preview)
```

---

## 3. Pull Request Details

- **Branch**: `feature/windows-portability-installer`
- **Target Branch**: `main`
- **PR Link**: [https://github.com/koppot/cloudbackup-windows/pull/1](https://github.com/koppot/cloudbackup-windows/pull/1)
- **Summary**: Phase 1 Development Preview — Windows Portability, PyInstaller standalone distribution, Inno Setup installer script, fail-closed rclone trust policy, safe subprocess API, GitHub Actions CI workflow, and Windows-first documentation.
