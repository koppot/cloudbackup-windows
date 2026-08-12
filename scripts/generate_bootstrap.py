"""
generate_bootstrap.py — Generate Plaintext Ground-Zero Recovery Guide for Windows Host
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BOOTSTRAP_TEMPLATE = """================================================================================
            CLOUD BACKUP FOR WINDOWS — GROUND-ZERO RESTORE GUIDE
================================================================================
DOCUMENT TYPE: Plaintext Unencrypted Ground-Zero Recovery Reference
STORAGE LOCATION: Google Drive / Cloud Storage Root ({base_remote}BOOTSTRAP.txt)
TARGET PATHS: C:\\ProgramData\\CloudBackup\\

In the event of complete system loss or disaster recovery on Windows, follow
these steps in sequence to restore all services, secrets, configuration, and data.

--------------------------------------------------------------------------------
STAGE 0: PREREQUISITES
--------------------------------------------------------------------------------
Before beginning recovery, ensure you have:
  1. A fresh Windows installation (Windows 10 / 11 or Windows Server) with
     Administrator privileges.
  2. Active internet connectivity.
  3. Access to your master password manager containing:
     - Cloud Storage Account (Google Drive / OneDrive) credentials / OAuth tokens
     - Rclone crypt passphrase (for {crypt_remote} / {secrets_crypt_remote})
     - Master encryption key & passwords
  4. Installed dependencies:
     - Python 3.10+ (added to System PATH)
     - rclone (installed in C:\\ProgramFiles\\rclone\\ or added to PATH)

--------------------------------------------------------------------------------
STAGE 1: BOOTSTRAP RCLONE & OAUTH
--------------------------------------------------------------------------------
1. Download & install official rclone executable for Windows:
   curl -O https://downloads.rclone.org/rclone-current-windows-amd64.zip
   Expand-Archive rclone-current-windows-amd64.zip -DestinationPath C:\\ProgramFiles\\rclone

2. Re-create base rclone remote setup ({base_remote_name}):
   rclone config
   - Name: {base_remote_name}
   - Type: drive (Google Drive)
   - Scope: drive (Full access)
   - Run interactive OAuth authorization in browser

3. Re-create crypt remotes using passphrases from password manager:
   - Name: {crypt_remote_name} (type: crypt, remote: {base_remote}adc-backup-data)
   - Name: {secrets_crypt_name} (type: crypt, remote: {base_remote}adc-backup-secrets)

4. Verify remote access:
   rclone lsd {crypt_remote}
   rclone lsd {secrets_crypt_remote}

--------------------------------------------------------------------------------
STAGE 2: RESTORE PACKAGE & PYTHON ENVIRONMENT
--------------------------------------------------------------------------------
1. Create system directory:
   mkdir C:\\ProgramData\\CloudBackup

2. Clone repository & set up Python virtual environment:
   cd C:\\ProgramData\\CloudBackup
   git clone https://github.com/koppot/cloudbackup-windows.git .
   python -m venv venv
   .\\venv\\Scripts\\activate.bat
   pip install -r requirements.txt


--------------------------------------------------------------------------------
STAGE 3: RESTORE CONFIGURATION & STATE DATABASE
--------------------------------------------------------------------------------
1. Restore core application configuration:
   rclone copy {crypt_remote}supermicro.local/config C:\\ProgramData\\CloudBackup\\config

2. Restore SQLite state database:
   rclone copy {crypt_remote}supermicro.local/database C:\\ProgramData\\CloudBackup\\
   sqlite3 C:\\ProgramData\\CloudBackup\\state.db "PRAGMA integrity_check;"

--------------------------------------------------------------------------------
STAGE 4: RESTORE SECRETS & RE-ENGAGE SERVICE
--------------------------------------------------------------------------------
1. Restore high-security secrets from dedicated secrets crypt remote:
   rclone copy {secrets_crypt_remote}supermicro.local/secrets C:\\ProgramData\\CloudBackup\\secrets

2. Re-register Windows Task Scheduler job or run web server:
   python windows\\web_server.py

--------------------------------------------------------------------------------
STAGE 5: VERIFICATION
--------------------------------------------------------------------------------
1. Open web browser to http://127.0.0.1:8765
2. Verify all configured source paths and cloud drive connections report Healthy.
================================================================================
"""


def generate_bootstrap(
    base_remote: str = "gdrive1:",
    crypt_remote: str = "gdrive1_crypt:",
    secrets_crypt_remote: str = "gdrive1_secrets_crypt:",
    output_path: str = "BOOTSTRAP.txt",
) -> str:
    base_remote_name = base_remote.rstrip(":")
    crypt_remote_name = crypt_remote.rstrip(":")
    secrets_crypt_name = secrets_crypt_remote.rstrip(":")

    text = BOOTSTRAP_TEMPLATE.format(
        base_remote=base_remote,
        base_remote_name=base_remote_name,
        crypt_remote=crypt_remote,
        crypt_remote_name=crypt_remote_name,
        secrets_crypt_remote=secrets_crypt_remote,
        secrets_crypt_name=secrets_crypt_name,
    )

    out = Path(output_path)
    out.write_text(text, encoding="utf-8")
    print(f"Generated Ground-Zero Recovery Guide: {out.resolve()}")
    return text


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate BOOTSTRAP.txt for Windows Disaster Recovery")
    parser.add_argument("--base-remote", default="gdrive1:", help="Base rclone remote name")
    parser.add_argument("--crypt-remote", default="gdrive1_crypt:", help="Crypt remote name")
    parser.add_argument("--secrets-remote", default="gdrive1_secrets_crypt:", help="Secrets crypt remote name")
    parser.add_argument("--output", default="BOOTSTRAP.txt", help="Output file path")
    args = parser.parse_args()

    generate_bootstrap(
        base_remote=args.base_remote,
        crypt_remote=args.crypt_remote,
        secrets_crypt_remote=args.secrets_remote,
        output_path=args.output,
    )
