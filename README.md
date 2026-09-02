# CloudBackup for Windows 🛡️

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-lightgray.svg)
![Installer](https://img.shields.io/badge/installer-CloudBackup--Setup.exe-success.svg)
![Status](https://img.shields.io/badge/status-Phase%201%20Development%20Preview-yellow.svg)

**CloudBackup for Windows** is a standalone, zero-knowledge encrypted backup solution designed specifically for Windows hosts. It provides nontechnical-user-friendly installation via `CloudBackup-Setup.exe`, automated cloud protection across Google Drive remotes, deduplication, and an intuitive local web dashboard.

---

## ⚡ Quick Start for Windows Users

1. **Download Installer**: Grab `CloudBackup-Setup.exe` from [GitHub Releases](https://github.com/koppot/cloudbackup-windows/releases).
2. **Install**: Double-click `CloudBackup-Setup.exe` to run the setup wizard.
3. **Onboarding**: Launch CloudBackup from your Start Menu. Your default browser will open to `http://127.0.0.1:8765`.
4. **Connect Storage**: Follow the UI wizard to sign in to your Google Account and select your backup folders.

> [!NOTE]  
> **No Administrative Rights Required at Runtime**: Elevation is requested only during installation to place binaries under `Program Files` and set up protected data directories in `ProgramData`. Normal daily operation runs without admin rights.

---

## 🔑 Key Features

- **Standalone Windows Executable**: No Python, Git, or command-line experience required for end users.
- **Zero-Knowledge Encryption**: AES-256 client-side encryption. Passphrases and tokens are never stored in plain text or logged.
- **Non-Destructive Copy Mode**: Default backups use `copy` semantics. Files on the cloud are **never** deleted by default.
- **Fail-Closed Security**: Pinned `rclone.exe` binary with SHA-256 manifest verification (`shared/rclone_manifest.json`). Prohibits bare `PATH` lookups.
- **Path Safety Validation**: Protection against directory traversal (`..`), NUL byte injection, and Windows reserved device names (`CON`, `PRN`, `NUL`).
- **Local Dashboard**: Access dashboard at `http://127.0.0.1:8765`.
- **Ground-Zero Recovery**: Auto-generates `BOOTSTRAP.txt` for complete disaster recovery.

---

## 📚 Documentation Index

- 📖 **[Windows User Installation Guide (INSTALL-WINDOWS.md)](INSTALL-WINDOWS.md)**
- 📖 **[User Guide (USER-GUIDE.md)](USER-GUIDE.md)**
- 🛡️ **[Administrator Guide (ADMIN-GUIDE.md)](ADMIN-GUIDE.md)**
- 🛠️ **[Build & Packaging Guide (BUILD-WINDOWS.md)](BUILD-WINDOWS.md)**
- 🚀 **[Release Process (RELEASE-PROCESS.md)](RELEASE-PROCESS.md)**
- 📝 **[Release Notes (RELEASE_NOTES.md)](RELEASE_NOTES.md)**
- 📋 **[Manual QA Checklist (docs/WINDOWS-MANUAL-QA.md)](docs/WINDOWS-MANUAL-QA.md)**

---

## 💻 Developer & Maintainer Setup

For maintainers running from Python source code:
```bat
git clone https://github.com/koppot/cloudbackup-windows.git
cd cloudbackup-windows
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt pyinstaller pytest
python -m pytest -v
```

Build the standalone PyInstaller package and Inno Setup installer:
```cmd
pyinstaller CloudBackup.spec
iscc installer/CloudBackupInstaller.iss
```

---

## 📄 License

Licensed under the [MIT License](LICENSE).
