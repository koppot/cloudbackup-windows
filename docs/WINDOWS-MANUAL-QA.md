# Manual QA Verification Checklist & 15-Gate Release Matrix — CloudBackup for Windows

This document defines the authoritative, reusable manual QA verification checklist and mandatory 15-step Release Gate matrix for **CloudBackup for Windows**.

Perform this checklist on a clean Windows 11 x64 virtual machine or isolated test system prior to publishing stable release tags (`v*`).

---

## Pre-Requisites & Test Boundaries

- [ ] Clean Windows 11 x64 environment without Python, Git, pip, or rclone installed in system `PATH`.
- [ ] CI-compiled installer executable `CloudBackup-Setup.exe`.
- [ ] Disposable Google Account with Google Drive storage for testing.
- [ ] Synthetic test data created using repository acceptance tooling (`tools/acceptance/generate_synthetic_data.py`).
- [ ] **NO PRODUCTION DATA OR PERSONAL GOOGLE ACCOUNTS MAY BE USED FOR VERIFICATION.**

---

## Automated Acceptance Tooling

CloudBackup provides automated PowerShell and Python helper scripts under `tools/acceptance/` to streamline VM test execution:

```powershell
# Run acceptance test suite on Windows 11 VM
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\tools\acceptance\run_vm_acceptance.ps1 -SourceDir "C:\CloudBackup-Acceptance-Test\source" -RestoreDir "C:\CloudBackup-Acceptance-Test\restore" -ArtifactDir "C:\CloudBackup-Acceptance-Test\artifacts"
```

### Included Acceptance Helpers:
1. `generate_synthetic_data.py`: Generates synthetic test dataset (plain text, binary, 5MB multichunk, spaces, Unicode `Ünicodë_测试_Файл.txt`, Windows punctuation, long paths, duplicate files).
2. `generate_manifest.py`: Computes cryptographic SHA-256 manifest (`JSON`, `CSV`, `TXT`).
3. `verify_restore.py`: Compares restored files against source manifest; verifies file counts, byte sizes, and SHA-256 digests.
4. `collect_evidence.py`: Gathers OS build, user privilege level, binary PATH availability, directory ACLs, listening sockets on port 8765, and Task Scheduler state.

---

## The 15-Gate Release Acceptance Matrix

All 15 gates below must pass cleanly before any stable release tag (`v*`) or release asset publication is permitted:

| Gate | Validation Target | Requirement & Verification Procedure |
|---|---|---|
| 1 | Artifact Retrieval | Download canonical build artifact `CloudBackup-Windows-x64-Release` from GitHub Actions CI. |
| 2 | Artifact Checksum | Verify local installer SHA-256 matches `checksums.sha256` manifest. |
| 3 | Clean Environment | Confirm test VM has zero pre-existing Python, Git, pip, or rclone binaries in system `PATH`. |
| 4 | Setup Installer Execution | Execute `CloudBackup-Setup.exe`; confirm UAC elevation prompt appears and Start Menu shortcut is created. |
| 5 | Installed Path Policy | Confirm binaries in `C:\Program Files\CloudBackup` and mutable state in `C:\ProgramData\CloudBackup`. |
| 6 | Standard User Launch | Sign in as standard non-admin user; launch application from Start Menu without UAC prompt; verify single-instance locking. |
| 7 | Loopback-Only Binding | Confirm web server binds to `127.0.0.1:8765` only; verify `--host 0.0.0.0` or hostile `HOST` env var are rejected. |
| 8 | Safe Onboarding | Complete Google OAuth authorization in browser using disposable test account; verify rclone config stored securely. |
| 9 | Non-Destructive Backup | Perform dry run and real `copy` backup of synthetic test folder; verify source files remain untouched. |
| 10 | Secret Redaction Audit | Inspect application logs and web UI; verify zero tokens, passphrases, or secrets are exposed. |
| 11 | Rclone Tamper Fail-Closed | Modify 1 byte of bundled `rclone.exe`; verify application halts with SHA-256 hash mismatch error. |
| 12 | Missing Rclone Fail-Closed | Delete bundled `rclone.exe` in isolated test copy; verify application fails closed without using system `PATH`. |
| 13 | Upgrade & Uninstall | Verify standard uninstall removes binaries/shortcuts while preserving `ProgramData\CloudBackup`; verify full purge flag deletes local state. |
| 14 | Task Scheduler | Create/enable scheduled task post-onboarding; verify non-elevated user execution without stored passwords. |
| 15 | Real Restore File Hash Match | Restore backup to separate staging path (`C:\CloudBackup-Acceptance-Test\restore`); verify **0 SHA-256 file mismatches**. |

---

## Detailed Manual QA Test Scenarios

### Scenario 1: Fresh Installation & Path Verification
- [ ] Double-click `CloudBackup-Setup.exe`. Confirm Windows UAC elevation prompt appears.
- [ ] Follow wizard to complete installation to `C:\Program Files\CloudBackup`.
- [ ] Verify directories created under `C:\ProgramData\CloudBackup` (`config`, `state`, `logs`, `temp`).
- [ ] Confirm Start Menu and Desktop shortcuts are created.
- [ ] Check option **Launch CloudBackup** and click **Finish**.
- [ ] Verify default browser opens to `http://127.0.0.1:8765`.

### Scenario 2: Standard User Privileges at Runtime
- [ ] Log in as a standard non-administrator Windows user.
- [ ] Launch CloudBackup from the Start Menu.
- [ ] Confirm dashboard loads without triggering UAC elevation prompts.
- [ ] Confirm non-admin user can perform backups and maintain state under `ProgramData\CloudBackup`.

### Scenario 3: Cloud Authorization & Initial Backup
- [ ] In Web UI, click **Setup Wizard / Add Remote**.
- [ ] Complete Google OAuth authorization in browser with a disposable Google Drive account.
- [ ] Verify remote connection status changes to `Healthy`.
- [ ] Click **Dry Run** and verify log output in web UI console.
- [ ] Click **Run Backup** and verify files upload successfully using copy semantics.

### Scenario 4: Path Security & Input Validation
- [ ] Attempt to add a source path containing reserved names (e.g. `C:\ProgramData\CON`). Confirm clear error message is returned.
- [ ] Attempt to add a source path with invalid characters. Confirm rejection.

### Scenario 5: Single Instance Locking & Host Binding Restrictions
- [ ] Attempt to launch a second instance of `CloudBackup.exe --server`.
- [ ] Verify warning message: "Another instance of CloudBackup is already running."
- [ ] Run `CloudBackup.exe --host 0.0.0.0` and verify instant termination with bind validation error.

### Scenario 6: Clean Uninstallation & Purge Options
- [ ] Open Windows **Settings > Apps > Installed apps**.
- [ ] Select **CloudBackup** and click **Uninstall**.
- [ ] Confirm binaries in `Program Files\CloudBackup` and shortcuts are removed.
- [ ] Verify backed-up data on Google Drive remains completely untouched.
