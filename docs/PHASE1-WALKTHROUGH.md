# Phase 1 Implementation & Security Remediation Walkthrough — CloudBackup for Windows (Phase 1 Development Preview)

> [!IMPORTANT]
> **Status**: **Phase 1 Development Preview**
> PR #1 is open, unmerged, and clean-mergeable. Automated CI builds on `windows-latest` have passed 100%. Before publishing a stable release or using CloudBackup to protect production data, complete the 15-step manual clean-Windows-VM acceptance checklist using a disposable cloud destination.

---

## 1. Executive Summary & Security Remediations

This pull request establishes Phase 1 Windows portability, standalone executable packaging, nontechnical installer creation, fail-closed security, and automated CI/CD pipeline for `cloudbackup-windows`.

### Key Security & Architectural Remediations Completed

1. **Removal of Embedded Credentials**:
   - Completely removed hard-coded passphrase strings from `windows/engine.py`.
   - `setup_wizard` and `_register_new_gdrive` dynamically generate crypt passphrases using `secrets.token_urlsafe(32)` or accept user-configured secrets.

2. **Fail-Closed Rclone Trust Policy**:
   - Missing manifest (`shared/rclone_manifest.json`), missing bundle executable, or SHA-256 hash mismatch halts execution immediately.
   - Pinned rclone Windows x64 binary (`v1.68.2`) hash: `dcbb5d188358df520b08a584df42a8e76161b30a90a62fefdd0001174d002122`.
   - Default resolution requires verified bundled binary. External overrides require explicit absolute paths (`os.path.isabs`). Implicit `PATH` lookups are prohibited.

3. **CI Rclone Staging & Hash Verification**:
   - GitHub Actions workflow stages pinned rclone x64, verifies SHA-256 against `shared/rclone_manifest.json`, and fails closed before running PyInstaller packaging.

4. **Environment Sanitization & Credential Leakage Prevention**:
   - Stripped inherited `RCLONE_CONFIG` and `RCLONE_CONF` environment variables in process execution (`shared/subprocess_utils.py` & `shared/rclone.py`).

5. **Loopback-Only Hosting Enforcement**:
   - Web server and CLI (`windows/cli.py` & `windows/web_server.py`) enforce loopback bind addresses (`127.0.0.1` / `localhost`). Non-loopback addresses are explicitly rejected.

6. **Least-Privilege Directory ACLs**:
   - Installer (`installer/CloudBackupInstaller.iss`) configures `C:\ProgramData\CloudBackup` subdirectories with least-privilege `system-full admins-full` access.

7. **Source Selection Directory Validation**:
   - Enforced `must_exist=True` directory validation before adding backup sources.

8. **Deferred Task Scheduler Management**:
   - Installer does NOT register scheduled tasks at setup. Added safe `schtasks.exe` creation, enablement, and disablement helpers (`create_scheduled_task`, `enable_scheduler`, `disable_scheduler`) triggered after onboarding.

9. **CI Workflow Pipeline & Concurrency**:
   - Workflow `.github/workflows/ci.yml` includes concurrency control (`cancel-in-progress: true`) and separated jobs (`test-windows`, `package-installer-windows`, `unit-tests-linux`).

---

## 2. Verified GitHub Actions CI Results

- **Workflow Run**: `33620170728`
- **Workflow Link**: [https://github.com/koppot/cloudbackup-windows/actions/runs/33620170728](https://github.com/koppot/cloudbackup-windows/actions/runs/33620170728)
- **Overall Status**: **PASSED (100% Success across 5 jobs)**

| Job Name | Runner | Status | Duration |
|---|---|---|---:|
| `Unit Tests on Windows (Python 3.10)` | `windows-latest` | ✓ PASSED | 30s |
| `Unit Tests on Windows (Python 3.11)` | `windows-latest` | ✓ PASSED | 31s |
| `Unit Tests on Windows (Python 3.12)` | `windows-latest` | ✓ PASSED | 23s |
| `Platform-Neutral Unit Tests` | `ubuntu-latest` | ✓ PASSED | 14s |
| `Build Executable & Installer` | `windows-latest` | ✓ PASSED | 2m 0s |

### Artifact & Checksum Hashes
- **Artifact Zip**: `CloudBackup-Windows-x64-Release` (ID: `9842645745`, Size: 56,267,998 bytes)
- **Artifact Zip SHA-256 Digest**: `d791e62691f0aa4b85e5c2b96509d499c5c0d24bd86cbbb7fcb4a89b910c8db4`
- **Pinned Bundled `rclone.exe` (v1.68.2 x64) SHA-256**: `dcbb5d188358df520b08a584df42a8e76161b30a90a62fefdd0001174d002122`

---

## 3. Manual Clean-Windows-VM Acceptance Checklist (15 Gates)

Before merging or publishing a tagged release, complete the following gates on a fresh Windows 11 x64 virtual machine:

1. [ ] **Download Artifact**: Download `CloudBackup-Windows-x64-Release` from CI run `33620170728`.
2. [ ] **Verify Hash**: Confirm artifact SHA-256 digest matches `d791e62691f0aa4b85e5c2b96509d499c5c0d24bd86cbbb7fcb4a89b910c8db4`.
3. [ ] **Clean VM Isolation**: Verify test VM has no pre-existing Python, Git, pip, or rclone.
4. [ ] **Install & Directory Check**: Execute `CloudBackup-Setup.exe`; confirm binaries under `C:\Program Files\CloudBackup` and data dirs under `C:\ProgramData\CloudBackup`.
5. [ ] **Standard User Operation**: Log in as standard user; launch Start Menu shortcut; verify no UAC prompt is requested.
6. [ ] **Loopback Binding**: Confirm server listens on `127.0.0.1:8765` only; verify no LAN socket is created.
7. [ ] **Onboarding Flow**: Complete cloud authorization using disposable Google Drive test account.
8. [ ] **Backup Execution**: Execute dry run and real `copy` backup of test folders with spaces, Unicode characters, long paths, and nested subdirectories.
9. [ ] **Secret Redaction Audit**: Inspect application logs (`C:\ProgramData\CloudBackup\logs\`) and dashboard UI; confirm no passphrases or tokens are exposed.
10. [ ] **Tamper Fail-Closed Test**: Modify bundled `rclone.exe` in VM; verify application halts with SHA-256 mismatch error.
11. [ ] **Missing Binary Fail-Closed Test**: Delete bundled `rclone.exe`; verify application fails closed without checking system `PATH`.
12. [ ] **Host Override Rejection**: Verify `--host 0.0.0.0` or `HOST=192.168.1.100` are rejected.
13. [ ] **Installer Upgrade & Uninstaller Purge**: Test setup upgrade and uninstaller options (data retention vs full purge).
14. [ ] **Task Scheduler Verification**: Test scheduled task creation post-onboarding; verify process execution under user identity.
15. [ ] **Real Restore Validation**: Perform end-to-end restore to a separate staging directory and verify SHA-256 file digests match originals.
