# CloudBackup for Windows — Administrator Guide

This guide details architecture, runtime privilege models, ACL security policies, rclone discovery trust rules, and disaster recovery procedures for system administrators.

---

## Directory Architecture & ACL Rationale

CloudBackup strictly separates application executables, protected machine configuration, database state, operational logs, and temporary files:

| Directory Path | Role | ACL Permissions |
|---|---|---|
| `C:\Program Files\CloudBackup` | Executables, static web assets, schema | Read & Execute only for standard users; Admin/Installer write |
| `C:\ProgramData\CloudBackup\config` | Protected configuration & `rclone.conf` | Admin & Application identity modify access |
| `C:\ProgramData\CloudBackup\state` | SQLite database (`state.db`) & lock | Application identity modify access |
| `C:\ProgramData\CloudBackup\logs` | Redacted log files | Application identity write; Support read-only |
| `C:\ProgramData\CloudBackup\temp` | Transient restore/dedup staging | Application identity modify access |

---

## Runtime Privilege Model

- **Installation**: Elevated privileges (`admin`) are requested by `CloudBackup-Setup.exe` to place files in `Program Files` and initialize `ProgramData` ACLs.
- **Normal Operation**: The web server and backup engine run under standard user privileges or dedicated limited service accounts. **No administrator rights are required for daily operation.**
- **Task Scheduler**: Automatic task scheduling is managed via `schtasks.exe`. The installer does NOT create scheduled tasks by default. Tasks are created idempotently via UI setup only after onboarding and explicit user consent.

---

## Rclone Security & Discovery Policy

CloudBackup enforces a fail-closed rclone discovery model:
1. **Bundled Binary (Default)**: Uses the pinned `bin/rclone.exe` bundled inside the PyInstaller distribution. SHA-256 hash is verified against `shared/rclone_manifest.json`.
2. **Explicit Absolute Path Override**: Permitted only when `rclone_bin` in `config.yaml` is set to an absolute path (e.g. `C:\Tools\rclone\rclone.exe`) and passes version compatibility validation.
3. **No PATH Fallback**: Bare `rclone` names or `PATH`-derived lookups are strictly prohibited to prevent binary hijacking.

---

## Ground-Zero Recovery (Disaster Recovery)

If a system experiences catastrophic failure:
1. Refer to `BOOTSTRAP.txt` generated at the root of your Google Drive backup.
2. Install a fresh Windows 10/11 system.
3. Re-install CloudBackup using `CloudBackup-Setup.exe`.
4. Restore `config` and `state.db` from your `_crypt` remote:
   ```cmd
   rclone copy gdrive1_crypt:supermicro.local/config C:\ProgramData\CloudBackup\config
   rclone copy gdrive1_crypt:supermicro.local/database C:\ProgramData\CloudBackup\state
   ```
5. Launch `CloudBackup.exe --server` and navigate to `http://127.0.0.1:8765`.
