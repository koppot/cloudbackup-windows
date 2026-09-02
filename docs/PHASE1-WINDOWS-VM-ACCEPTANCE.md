# Phase 1 Stable-Release Acceptance Result — CloudBackup for Windows

> [!IMPORTANT]
> **FINAL DECISION**: **NOT READY FOR STABLE RELEASE** (Pending Manual Clean-VM Interactive Gates)
> - **Branch**: `feature/phase1-windows-vm-acceptance`
> - **Commit**: `b037bee`
> - **Release Gate Issue**: [#2 — Phase 1 Release Gate — Clean Windows 11 VM Installer, Backup, and Restore Acceptance](https://github.com/koppot/cloudbackup-windows/issues/2)
> - **Primary Blocker**: Interactive GUI installation, Google OAuth authorization, disposable-cloud backup execution, and end-to-end restore SHA-256 hash comparison on an isolated Windows 11 x64 VM remain **PENDING** human VM execution.

---

## 1. Executive Summary & Repository Identifiers

- **Repository**: [https://github.com/koppot/cloudbackup-windows](https://github.com/koppot/cloudbackup-windows)
- **Target Branch**: `main`
- **Feature Branch**: `feature/phase1-windows-vm-acceptance`
- **Current Head Commit**: `b037bee`
- **Acceptance Tooling**: Added `tools/acceptance/` (`generate_synthetic_data.py`, `generate_manifest.py`, `verify_restore.py`, `collect_evidence.py`, `run_vm_acceptance.ps1`, `run_acceptance.py`) and automated pytest suite `tests/test_acceptance_tooling.py`.

---

## 2. CI/CD Pipeline & Provenance Verification

- **Automated Pytest Suite**: **89/89 PASSED** (including acceptance tooling self-verification).
- **Source Pattern Scan (`python scripts/scan_secrets.py`)**: PASSED (0 secret findings).
- **Artifact Pattern Scan (`python scripts/scan_secrets.py --scan-artifacts`)**: PASSED (0 secret findings in PyInstaller executable or Inno Setup installer).
- **Pinned Bundled `rclone.exe` (v1.68.2 x64) SHA-256**: `dcbb5d188358df520b08a584df42a8e76161b30a90a62fefdd0001174d002122`

---

## 3. Mandatory Acceptance Gate Status (15 Gates)

| Gate | Validation Target | Result | Evidence & Operational Summary |
|---|---|---|---|
| 1 | Artifact Retrieval | **PASS (CI)** | PyInstaller executable distribution and Inno Setup installer compiled via GitHub Actions CI workflow (`.github/workflows/ci.yml`). |
| 2 | Artifact Checksum Verification | **PASS (CI)** | Local and CI checksum manifests match computed SHA-256 digests (`checksums.sha256`). |
| 3 | Clean Environment Confirmation | **PENDING VM** | Requires fresh Windows 11 x64 VM with zero pre-existing Python, Git, pip, or rclone binaries. |
| 4 | Setup Installer Execution | **PENDING VM** | Inno Setup installer compilation verified (`CloudBackup-Setup.exe`). Interactive GUI setup and UAC prompt pending VM execution. |
| 5 | Installed Path Policy | **PASS (Code)** | Binaries forced to `C:\Program Files\CloudBackup`; state to `C:\ProgramData\CloudBackup` (`shared/paths.py`). |
| 6 | Standard User Launch & Locking | **PASS (Code/Tests)** | `SingleInstanceLock` unit-tested; standard non-admin runtime path verified (`tests/test_frozen_integration.py`). |
| 7 | Loopback-Only Binding | **PASS (Code/Tests)** | `windows/web_server.py` enforces `127.0.0.1:8765`. Rejects `0.0.0.0` or external bind attempts (`tests/test_frozen_integration.py`). |
| 8 | Safe Onboarding | **PENDING VM** | Complete OAuth using disposable Google Drive test account. |
| 9 | Non-Destructive Backup | **PENDING VM** | Perform dry run and real `copy` backup of synthetic files (`tools/acceptance/generate_synthetic_data.py`). |
| 10 | Secret Redaction Audit | **PASS (Code/Tests)** | Sensitive string redaction verified in `shared/subprocess_utils.py` and `tests/test_subprocess_safety.py`. |
| 11 | Rclone Tamper Fail-Closed | **PASS (Code/Tests)** | SHA-256 hash verification against `shared/rclone_manifest.json` halts on tampered binary (`tests/test_rclone_discovery.py`). |
| 12 | Missing Rclone Fail-Closed | **PASS (Code/Tests)** | `resolve_rclone_binary` halts immediately if bundled executable is missing; ignores system `PATH`. |
| 13 | Upgrade & Uninstall | **PASS (Code)** | Inno Setup directives preserve `ProgramData\CloudBackup` on standard uninstall; full purge on flag (`installer/CloudBackupInstaller.iss`). |
| 14 | Task Scheduler Post-Onboarding | **PASS (Code)** | Deferred `schtasks.exe` creation helpers implemented in `windows/engine.py`. Default installer registers 0 scheduled tasks. |
| 15 | Real Restore File Hash Match | **PENDING VM** | Restore to `C:\CloudBackup-Acceptance-Test\restore` and verify 0 SHA-256 mismatches using `tools/acceptance/verify_restore.py`. |

---

## 4. Synthetic Test Dataset Details

- **Dataset Generator**: `tools/acceptance/generate_synthetic_data.py`
- **Default Location**: `C:\CloudBackup-Acceptance-Test\source`
- **Total Test Files**: 12 files (5,411,295 bytes total)
- **Composition**: Plain text, binary patterns, 5MB multichunk binary, spaces in file/folder names, Unicode characters (`Ünicodë_测试_Файл.txt`), Windows-permitted punctuation (`file-1.2_test(1)[2]{3}#4$5%6&7.txt`), long nested paths (130+ chars), duplicate content files.
- **Safety Statement**: Zero real personal, server, media, customer, credential, or production data is used.

---

## 5. Acceptance Tooling Verification Summary

The acceptance test suite in `tools/acceptance/` was self-verified via `tools/acceptance/run_acceptance.py` and `tests/test_acceptance_tooling.py`:

```text
================================================================================
 CloudBackup Phase 1 Acceptance Tooling Self-Verification
================================================================================

[1] Testing Synthetic Dataset Creation... PASS (12 files, 5,411,295 bytes)
[2] Testing Checksum Manifest Generation... PASS (JSON, CSV, TXT saved)
[3] Simulating Perfect Restore Tree... PASS (Tree mirrored)
[4] Testing Restore Verification Engine... PASS (0 SHA-256 mismatches)
[5] Testing Intentionally Corrupted Restore Detection... PASS (Detected SHA-256 corruption)
[6] Testing Environment Evidence Collector... PASS (7 evidence sections collected)
```

---

## 6. Remaining Limitations & Blockers for Stable Release

1. **Interactive Clean Windows 11 VM Acceptance**: Gates 3, 4, 8, 9, and 15 require manual GUI execution on a fresh Windows 11 x64 virtual machine using `tools/acceptance/run_vm_acceptance.ps1` and a disposable test Google account.
2. **Code Signing**: Executables and installer are currently unsigned.

---

## 7. Final Decision

```text
================================================================================
FINAL ACCEPTANCE DECISION: NOT READY FOR STABLE RELEASE
================================================================================
```

CloudBackup for Windows remains at **Phase 1 Development Preview**. Stable Release Candidate status is **BLOCKED** until all 5 pending manual clean-VM gates (Gates 3, 4, 8, 9, 15) are executed on a clean Windows 11 VM and produce 0 SHA-256 mismatches on restore.
