# Manual QA Verification Checklist — CloudBackup for Windows

Perform this checklist on a clean Windows 11 x64 virtual machine or test system prior to publishing releases.

---

## Pre-Requisites

- [ ] Clean Windows 11 x64 environment without Python, Git, pip, or rclone installed in system PATH.
- [ ] Installer executable `CloudBackup-Setup.exe`.
- [ ] Active Google Account for testing.

---

## Test Scenarios

### Scenario 1: Fresh Installation & Onboarding
- [ ] Launch `CloudBackup-Setup.exe`. Confirm Windows UAC elevation prompt appears.
- [ ] Follow wizard to complete installation to `C:\Program Files\CloudBackup`.
- [ ] Verify directories created under `C:\ProgramData\CloudBackup` (`config`, `state`, `logs`, `temp`).
- [ ] Confirm Start Menu and Desktop shortcuts are created.
- [ ] Check option **Launch CloudBackup** and click **Finish**.
- [ ] Verify default browser opens to `http://127.0.0.1:8765`.

### Scenario 2: Standard User Privileges at Runtime
- [ ] Log in as a standard non-administrator Windows user.
- [ ] Launch CloudBackup from the Start Menu.
- [ ] Confirm dashboard loads without triggering UAC elevation prompts.

### Scenario 3: Cloud Authorization & Initial Backup
- [ ] In Web UI, click **Setup Wizard / Add Remote**.
- [ ] Complete Google OAuth authorization in browser.
- [ ] Verify remote connection status changes to `Healthy`.
- [ ] Click **Dry Run** and verify log output in web UI console.
- [ ] Click **Run Backup** and verify files upload successfully.

### Scenario 4: Path Security & Input Validation
- [ ] Attempt to add a source path containing reserved names (e.g. `C:\ProgramData\CON`). Confirm clear error message is returned.
- [ ] Attempt to add a source path with invalid characters. Confirm rejection.

### Scenario 5: Single Instance Locking
- [ ] Attempt to launch a second instance of `CloudBackup.exe --server`.
- [ ] Verify warning message: "Another instance of CloudBackup is already running."

### Scenario 6: Clean Uninstallation
- [ ] Open Windows **Settings > Apps > Installed apps**.
- [ ] Select **CloudBackup** and click **Uninstall**.
- [ ] Confirm binaries in `Program Files\CloudBackup` and shortcuts are removed.
- [ ] Verify backed-up data on Google Drive remains completely untouched.
