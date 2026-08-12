#!/usr/bin/env python3
"""
scripts/generate_bootstrap.py — Generate and optionally upload BOOTSTRAP.txt recovery guide.

Reads config.yaml (if present) to resolve primary base remote, writes plaintext
ground-zero restore guide, and optionally uploads it to root of remote using rclone.

Usage:
    python3 scripts/generate_bootstrap.py [--config /opt/adc-backup/config.yaml]
                                           [--output /opt/adc-backup/BOOTSTRAP.txt]
                                           [--upload]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Add project root to sys.path if needed
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import yaml
except ImportError:
    yaml = None


BOOTSTRAP_TEMPLATE = """================================================================================
                    ADC BACKUP SYSTEM — GROUND-ZERO RESTORE GUIDE
================================================================================
DOCUMENT TYPE: Plaintext Unencrypted Ground-Zero Recovery Reference
STORAGE LOCATION: Google Drive Root ({base_remote}BOOTSTRAP.txt)
TARGET PATHS: /opt/adc-backup/

In the event of complete system loss or disaster recovery, follow these steps in
sequence to restore all services, secrets, configuration, and data.

--------------------------------------------------------------------------------
STAGE 0: PREREQUISITES
--------------------------------------------------------------------------------
Before beginning recovery, ensure you have:
  1. A fresh Linux installation (Ubuntu 22.04 LTS / 24.04 LTS recommended) with
     root or sudo privileges.
  2. Active internet connectivity.
  3. Access to your master password manager containing:
     - Google Account OAuth credentials / recovery access
     - Rclone crypt passphrase (for {crypt_remote} / {secrets_crypt_remote})
     - SSH key passphrases & database passwords
  4. Basic build dependencies:
     apt update && apt install -y python3 python3-pip git curl rsync unzip sqlite3

--------------------------------------------------------------------------------
STAGE 1: BOOTSTRAP RCLONE & OAUTH
--------------------------------------------------------------------------------
1. Install official rclone binary:
   curl https://rclone.org/install.sh | bash

2. Re-create base rclone remote setup ({base_remote}):
   rclone config
   - Name: {base_remote_name}
   - Type: drive (Google Drive)
   - Scope: drive (Full access)
   - Run interactive OAuth authorization:
     rclone authorize "drive"

3. Re-create crypt remotes using passphrases from password manager:
   - Name: {crypt_remote_name} (type: crypt, remote: {base_remote}backup)
   - Name: {secrets_crypt_name} (type: crypt, remote: {base_remote}secrets)

4. Verify remote access:
   rclone lsd {crypt_remote}
   rclone lsd {secrets_crypt_remote}

--------------------------------------------------------------------------------
STAGE 2: RESTORE PACKAGE LIST
--------------------------------------------------------------------------------
1. Create system directory:
   mkdir -p /opt/adc-backup

2. Download package definitions from crypt remote:
   rclone copy {crypt_remote}linux/packages /opt/adc-backup/packages

3. Restore Debian/Ubuntu packages:
   dpkg --set-selections < /opt/adc-backup/packages/dpkg-selections.txt
   apt-get dselect-upgrade -y

4. Restore Python virtual environments / pip packages:
   pip3 install -r /opt/adc-backup/packages/requirements.txt

--------------------------------------------------------------------------------
STAGE 3: RESTORE CONFIGURATION
--------------------------------------------------------------------------------
1. Restore core application and system configuration:
   rclone copy {crypt_remote}linux/config /etc

2. Restore ADC Backup System configuration:
   rclone copy {crypt_remote}linux/adc-config /opt/adc-backup/

3. Verify configuration integrity:
   ls -la /opt/adc-backup/config.yaml

--------------------------------------------------------------------------------
STAGE 4: RESTORE DATABASES
--------------------------------------------------------------------------------
1. Restore SQLite state database:
   rclone copy {crypt_remote}linux/database /opt/adc-backup/
   sqlite3 /opt/adc-backup/state.db "PRAGMA integrity_check;"

2. Restore MySQL / MariaDB (if applicable):
   rclone copy {crypt_remote}linux/mysql /tmp/mysql_backup
   mysql -u root -p < /tmp/mysql_backup/all_databases.sql
   rm -rf /tmp/mysql_backup

--------------------------------------------------------------------------------
STAGE 5: RESTORE SECRETS
--------------------------------------------------------------------------------
1. Restore high-security secrets from dedicated secrets crypt remote:
   rclone copy {secrets_crypt_remote}linux/secrets /

2. Enforce strict permissions on sensitive files:
   chmod 600 /etc/ssl/private/* 2>/dev/null || true
   chmod 700 /root/.ssh
   chmod 600 /root/.ssh/authorized_keys /root/.ssh/id_* 2>/dev/null || true
   chmod 600 /opt/adc-backup/rclone.conf
   chmod 600 /opt/adc-backup/auth.json 2>/dev/null || true

--------------------------------------------------------------------------------
STAGE 6: SERVICE RESTORATION
--------------------------------------------------------------------------------
1. Reload systemd daemon:
   systemctl daemon-reload

2. Enable and start core infrastructure services:
   systemctl enable --now tailscaled
   systemctl enable --now nginx 2>/dev/null || true
   systemctl enable --now mysql 2>/dev/null || true

3. Verify Tailscale mesh network status:
   tailscale status

--------------------------------------------------------------------------------
STAGE 7: BACKUP SYSTEM SELF-RESTORE
--------------------------------------------------------------------------------
1. Restore systemd unit file for ADC Backup:
   cp /opt/adc-backup/systemd/adc-backup.service /etc/systemd/system/
   systemctl daemon-reload
   systemctl enable --now adc-backup.service

2. Verify service health and access UI:
   systemctl status adc-backup.service
   curl -I http://127.0.0.1:8080/health

3. Re-verify Google Drive connection and token status in the ADC Backup UI.
================================================================================
"""


def get_remote_info(config_path: str) -> dict:
    """Extract base and crypt remote names from config.yaml if available."""
    info = {
        "base_remote": "gdrive1:",
        "base_remote_name": "gdrive1",
        "crypt_remote": "gdrive1_crypt:",
        "crypt_remote_name": "gdrive1_crypt",
        "secrets_crypt_remote": "gdrive1_secrets_crypt:",
        "secrets_crypt_name": "gdrive1_secrets_crypt",
        "rclone_conf": "/opt/adc-backup/rclone.conf",
    }
    cfg_file = Path(config_path).expanduser().resolve()
    if cfg_file.exists() and yaml is not None:
        try:
            with open(cfg_file, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            if isinstance(raw, dict):
                info["rclone_conf"] = raw.get("rclone_conf", info["rclone_conf"])
                drives = raw.get("drives", {}).get("remotes", [])
                if drives and isinstance(drives, list):
                    first = drives[0]
                    base = first.get("base_remote", "gdrive1:")
                    crypt = first.get("crypt_remote", "gdrive1_crypt:")
                    secrets_crypt = first.get("secrets_crypt_remote", "gdrive1_secrets_crypt:")

                    info["base_remote"] = base if base.endswith(":") else base + ":"
                    info["base_remote_name"] = info["base_remote"].rstrip(":")
                    info["crypt_remote"] = crypt if crypt.endswith(":") else crypt + ":"
                    info["crypt_remote_name"] = info["crypt_remote"].rstrip(":")
                    if secrets_crypt:
                        info["secrets_crypt_remote"] = (
                            secrets_crypt if secrets_crypt.endswith(":") else secrets_crypt + ":"
                        )
                        info["secrets_crypt_name"] = info["secrets_crypt_remote"].rstrip(":")
        except Exception as e:
            print(f"Warning: could not parse {cfg_file}: {e}")
    return info


def generate_bootstrap(config_file: str, output_file: str, upload: bool) -> None:
    info = get_remote_info(config_file)
    content = BOOTSTRAP_TEMPLATE.format(**info)

    out_path = Path(output_file).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(content)

    print(f"BOOTSTRAP.txt successfully written to: {out_path}")

    if upload:
        base_remote = info["base_remote"]
        rclone_conf = info["rclone_conf"]
        target = f"{base_remote}BOOTSTRAP.txt"
        print(f"Uploading BOOTSTRAP.txt to plain remote: {target} ...")

        cmd = ["rclone", "copyto", str(out_path), target]
        if Path(rclone_conf).exists():
            cmd.extend(["--config", rclone_conf])

        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"Successfully uploaded BOOTSTRAP.txt to {target}")
            else:
                print(f"Failed to upload BOOTSTRAP.txt: {res.stderr.strip()}")
                sys.exit(res.returncode)
        except FileNotFoundError:
            print("ERROR: rclone binary not found in PATH. Install rclone to upload.")
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and upload ground-zero BOOTSTRAP.txt guide"
    )
    parser.add_argument(
        "--config",
        default="/opt/adc-backup/config.yaml",
        help="Path to config.yaml (default: /opt/adc-backup/config.yaml)",
    )
    parser.add_argument(
        "--output",
        default="/opt/adc-backup/BOOTSTRAP.txt",
        help="Path for generated output file (default: /opt/adc-backup/BOOTSTRAP.txt)",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload BOOTSTRAP.txt to unencrypted root of base remote using rclone",
    )
    args = parser.parse_args()
    generate_bootstrap(args.config, args.output, args.upload)


if __name__ == "__main__":
    main()
