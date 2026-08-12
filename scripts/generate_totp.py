#!/usr/bin/env python3
"""
scripts/generate_totp.py — Setup TOTP authentication and admin password for ADC Backup System.

Generates a TOTP secret, prompts for password, hashes it using bcrypt (or SHA-256 fallback),
and saves credentials to auth.json.

Usage:
    python3 scripts/generate_totp.py [--auth-file /opt/adc-backup/auth.json]
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import pyotp
except ImportError:
    print("ERROR: pyotp module is required. Install with: pip install pyotp")
    sys.exit(1)

try:
    import bcrypt
    HAS_BCRYPT = True
except ImportError:
    HAS_BCRYPT = False

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False


def hash_password(password: str) -> str:
    """Hash password with bcrypt if available, else SHA-256 fallback."""
    if HAS_BCRYPT:
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
        return hashed.decode("utf-8")
    else:
        salt = os.urandom(16).hex()
        digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        return f"sha256${salt}${digest}"


def generate_totp_setup(auth_file: str) -> None:
    auth_path = Path(auth_file).expanduser().resolve()

    # 1. Generate TOTP secret and provisioning URI
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name="admin@adc-backup", issuer_name="ADC Backup System")

    print("\n" + "=" * 60)
    print("      ADC BACKUP SYSTEM — INITIAL AUTHENTICATION SETUP")
    print("=" * 60)
    print(f"\nTOTP Secret Key: {secret}\n")
    print(f"Provisioning URI:\n{uri}\n")

    # 2. Print ASCII QR Code if qrcode library is installed
    if HAS_QRCODE:
        print("Scan the QR code below using your Authenticator App:")
        qr = qrcode.QRCode()
        qr.add_data(uri)
        qr.print_ascii(invert=True)
    else:
        print("NOTE: 'qrcode' package not found. You can enter the TOTP Secret Key manually into your app.")

    print("\nScan QR code with your authenticator app")
    print("-" * 60)

    # 3. Prompt for Admin Password
    while True:
        password = getpass.getpass("Enter new admin password: ")
        if not password:
            print("Password cannot be empty. Please try again.")
            continue
        confirm = getpass.getpass("Confirm admin password: ")
        if password != confirm:
            print("Passwords do not match. Please try again.")
            continue
        break

    password_hash = hash_password(password)

    # 4. Save to auth.json
    auth_data = {
        "totp_secret": secret,
        "password_hash": password_hash,
        "hash_algorithm": "bcrypt" if HAS_BCRYPT else "sha256",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    auth_path.parent.mkdir(parents=True, exist_ok=True)
    with open(auth_path, "w", encoding="utf-8") as fh:
        json.dump(auth_data, fh, indent=2)

    try:
        os.chmod(auth_path, 0o600)
    except OSError:
        pass

    print(f"\nSuccessfully configured authentication details in: {auth_path}")
    print("Keep your TOTP secret and password safe!")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate TOTP & admin password for ADC Backup System"
    )
    parser.add_argument(
        "--auth-file",
        default="/opt/adc-backup/auth.json",
        help="Target path for auth.json (default: /opt/adc-backup/auth.json)",
    )
    args = parser.parse_args()
    generate_totp_setup(args.auth_file)


if __name__ == "__main__":
    main()
