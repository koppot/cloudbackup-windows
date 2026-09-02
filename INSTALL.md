# CloudBackup for Windows — Installation Overview

CloudBackup for Windows provides two installation pathways:

1. **Nontechnical End-User Installation (Recommended)**: Use the `CloudBackup-Setup.exe` installer for an automated, zero-technical-knowledge setup.
2. **Maintainer / Developer Installation**: Run directly from Python source code for development and testing.

---

## 1. Nontechnical End-User Installation

Please refer to **[INSTALL-WINDOWS.md](INSTALL-WINDOWS.md)** for step-by-step graphical instructions.

- Download `CloudBackup-Setup.exe` from GitHub Releases.
- Run setup wizard to install to `C:\Program Files\CloudBackup`.
- Launch from Start Menu. Daily use requires **NO administrator rights**.

---

## 2. Developer / Maintainer Source Setup

### Prerequisites
- Windows 10/11 x64
- Python 3.10+ x64

### Steps
```cmd
git clone https://github.com/koppot/cloudbackup-windows.git
cd cloudbackup-windows
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt pyinstaller pytest
python -m pytest -v
python windows\cli.py --server
```
Navigate to `http://127.0.0.1:8765` in your browser.
