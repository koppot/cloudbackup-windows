#!/usr/bin/env bash
# ==============================================================================
# ADC Backup System — Linux Automated Multi-Drive Setup (Add-GoogleDrive.sh)
# Exact Linux parity port of Windows Add-GoogleDrive.ps1
# ==============================================================================

set -euo pipefail

RCLONE_BIN="${RCLONE_BIN:-/usr/bin/rclone}"
RCLONE_CONF="${RCLONE_CONF:-/opt/adc-backup/rclone.conf}"
DB_PATH="${DB_PATH:-/opt/adc-backup/db/state.db}"
PYTHON_BIN="${PYTHON_BIN:-/opt/adc-backup/venv/bin/python3}"

echo "==================================================="
echo "   ADD ADDITIONAL GOOGLE DRIVE ACCOUNTS TO BACKUP   "
echo "==================================================="
echo ""

NUM="${1:-}"
if [ -z "${NUM}" ]; then
  read -rp "Enter the drive number to add (e.g. 3 for gdrive3, 4 for gdrive4): " NUM
fi

if ! [[ "${NUM}" =~ ^[0-9]+$ ]]; then
  echo "[ERROR] Invalid drive number. Exiting." >&2
  exit 1
fi

BASE_REMOTE="gdrive${NUM}"
CRYPT_REMOTE="${BASE_REMOTE}_crypt"
SECRETS_CRYPT_REMOTE="${BASE_REMOTE}_secrets_crypt"
REMOTE_DATA_FOLDER="${BASE_REMOTE}:adc-backup-data"
REMOTE_SECRETS_FOLDER="${BASE_REMOTE}:adc-backup-secrets"
PASSPHRASE="SuperMicroBackup2026!Secure"

echo ""
echo "[1/4] Starting Google OAuth authorization for ${BASE_REMOTE}..."
echo "Run the command below in your web browser or terminal to authorize:"
echo ""
echo "  ${RCLONE_BIN} authorize \"drive\""
echo ""
read -rp "Paste the resulting JSON token here: " TOKEN_JSON

if [ -z "${TOKEN_JSON}" ]; then
  echo "[ERROR] Token cannot be empty. Exiting." >&2
  exit 1
fi

# 1. Create Base Remote
echo ""
echo "[2/4] Configuring base remote ${BASE_REMOTE}..."
"${RCLONE_BIN}" --config "${RCLONE_CONF}" config create "${BASE_REMOTE}" drive scope drive token "${TOKEN_JSON}"

# 2. Create Crypt Remotes
echo "[3/4] Configuring encrypted remotes ${CRYPT_REMOTE} and ${SECRETS_CRYPT_REMOTE}..."
"${RCLONE_BIN}" --config "${RCLONE_CONF}" config create "${CRYPT_REMOTE}" crypt remote "${REMOTE_DATA_FOLDER}" filename_encryption standard directory_name_encryption true password "${PASSPHRASE}"
"${RCLONE_BIN}" --config "${RCLONE_CONF}" config create "${SECRETS_CRYPT_REMOTE}" crypt remote "${REMOTE_SECRETS_FOLDER}" filename_encryption standard directory_name_encryption true password "${PASSPHRASE}"

# 3. Create Remote Folders
echo "[4/4] Creating remote backup directories on ${BASE_REMOTE}..."
"${RCLONE_BIN}" --config "${RCLONE_CONF}" mkdir "${REMOTE_DATA_FOLDER}" || true
"${RCLONE_BIN}" --config "${RCLONE_CONF}" mkdir "${REMOTE_SECRETS_FOLDER}" || true

# 4. Register in SQLite Database Catalog
"${PYTHON_BIN}" -c "
import sys
sys.path.insert(0, '/opt/adc-backup')
from shared import database as db
from datetime import datetime, timezone

db.add_remote({
    'name': '${BASE_REMOTE}',
    'provider': 'drive',
    'base_remote': '${BASE_REMOTE}:',
    'crypt_remote': '${CRYPT_REMOTE}:',
    'secrets_crypt_remote': '${SECRETS_CRYPT_REMOTE}:',
    'priority': ${NUM},
    'authorized_at': datetime.now(timezone.utc).isoformat(),
    'status': 'ok'
}, '${DB_PATH}')
print('Registered ${BASE_REMOTE} in SQLite database state catalog successfully.')
"

echo ""
echo "==================================================="
echo " SUCCESS! Drive ${BASE_REMOTE} added and active."
echo " Refresh your dashboard at https://asiandvdclub.org/backup/drives to view."
echo "==================================================="
