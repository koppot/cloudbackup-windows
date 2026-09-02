#!/usr/bin/env python3
"""
scripts/scan_secrets.py — Repository and Artifact Secret Scanner

Scans repository files for accidental secret leakage:
  - rclone.conf files
  - .env files
  - OAuth access/refresh tokens (e.g. ya29.)
  - Private keys / PEM blocks
  - Hardcoded password assignments
  - Sensitive environment configurations
"""

import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()

SECRET_PATTERNS = [
    (re.compile(r"-----BEGIN\s+(EC|RSA|DSA|OPENSSH)?\s*PRIVATE\s+KEY-----"), "Private Key"),
    (re.compile(r"ya29\.[0-9A-Za-z_-]{20,}"), "Google OAuth Access Token"),
    (re.compile(r"1//0[0-9A-Za-z_-]{20,}"), "Google OAuth Refresh Token"),
    (re.compile(r"SuperMicroBackup[0-9A-Za-z!@#$%^&*]+"), "Hardcoded Crypt Password"),
    (re.compile(r"password\s*=\s*['\"][^'\"]{8,}['\"]"), "Hardcoded Password Assignment"),
]

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", "build", "dist", ".pytest_cache"}
ALLOWED_SECRET_EXTENSIONS = {".py", ".md", ".iss", ".spec", ".json", ".sql", ".txt", ".yml", ".yaml"}


def scan_repository() -> int:
    print("=" * 70)
    print("      CLOUD BACKUP — REPOSITORY SECRET SCANNER")
    print("=" * 70)

    findings = []

    for root, dirs, files in os.walk(ROOT_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

        for file in files:
            file_path = Path(root) / file
            rel_path = file_path.relative_to(ROOT_DIR)

            # Check for forbidden secret files
            if file == "rclone.conf" or file.startswith(".rclone"):
                findings.append(f"FORBIDDEN FILE DETECTED: {rel_path}")
            if file == ".env" or (file.startswith(".env.") and not file.endswith(".example")):
                findings.append(f"UNPROTECTED ENV FILE DETECTED: {rel_path}")

            if file_path.suffix.lower() not in ALLOWED_SECRET_EXTENSIONS:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                for pattern, desc in SECRET_PATTERNS:
                    matches = pattern.findall(content)
                    if matches and rel_path != Path("scripts/scan_secrets.py"):
                        findings.append(f"SECRET PATTERN DETECTED ({desc}) in {rel_path}")
            except Exception as exc:
                print(f"[WARN] Failed to read {rel_path}: {exc}")

    if findings:
        print("\n❌ SECRET SCAN FAILED — Potential secrets detected:")
        for f in findings:
            print(f"   - {f}")
        return 1

    print("✅ SECRET SCAN PASSED: Zero plain-text credentials, tokens, or forbidden files found.")
    return 0


if __name__ == "__main__":
    sys.exit(scan_repository())
