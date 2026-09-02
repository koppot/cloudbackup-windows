# CloudBackup for Windows — System Architecture

This document describes the high-level architecture, module boundaries, directory structure, and security controls of CloudBackup for Windows.

---

## High-Level Architecture

```text
[ Windows 10/11 User Interface ]
       │
       ▼ (http://127.0.0.1:8765)
[ windows/web_server.py (HTTP Server) ]
       │
       ├──► [ shared/paths.py (Path Validation & Directory Policy) ]
       ├──► [ shared/database.py (SQLite state.db WAL Mode) ]
       └──► [ windows/engine.py (Backup Engine & Task Scheduler) ]
                 │
                 ▼ (Argument List Process Calls / Credentials Redacted)
            [ shared/subprocess_utils.py & shared/rclone.py ]
                 │
                 ▼ (SHA-256 Validated Bundled Executable)
            [ bin/rclone.exe (AES-256 Crypt Engine) ]
                 │
                 ▼ (TLS 1.3 / OAuth 2.0)
            [ Google Drive Cloud Remote (_crypt) ]
```

---

## Directory Roles & Privilege Isolation

- **Binaries (`C:\Program Files\CloudBackup`)**: Immutable executables, PyInstaller dependencies, static web assets. Read-only for non-admin users.
- **Protected Configuration (`C:\ProgramData\CloudBackup\config`)**: `rclone.conf` and `auth.json`. Access restricted to application identity.
- **State & Database (`C:\ProgramData\CloudBackup\state`)**: SQLite database (`state.db`) operating in WAL mode, job logs, single-instance lock file (`cloudbackup.lock`).
- **Logs (`C:\ProgramData\CloudBackup\logs`)**: Immutable per-run log files with automatically redacted passphrases and tokens.
- **Temporary Staging (`C:\ProgramData\CloudBackup\temp`)**: Transient restore staging directory.

---

## Core Security Controls

1. **Path Safety Validation (`shared/paths.py`)**: All paths are normalized with `pathlib.Path`. Rejects NUL bytes, Windows reserved device names (`CON`, `PRN`, `AUX`), and traversal escapes.
2. **Fail-Closed Rclone Discovery (`shared/rclone.py`)**: Uses bundled `bin/rclone.exe` verified against `shared/rclone_manifest.json`. Bare `PATH` lookups are prohibited.
3. **Safe Subprocess Execution (`shared/subprocess_utils.py`)**: Subprocesses use argument arrays only (`shell=False`). Passphrases, bearer tokens, and OAuth keys are redacted before logging.
4. **Deferred Task Scheduling**: The installer does NOT create Task Scheduler tasks by default. Automatic backup tasks are registered idempotently only after onboarding and explicit user enablement.
