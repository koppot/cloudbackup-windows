#!/usr/bin/env bash
# ==============================================================================
# ADC Backup System — Ground-Zero Bare-Metal / Cloud Server Restoration Script
#
# Purpose:
#   Takes a fresh Linux installation (Ubuntu 22.04 LTS) and restores an exact,
#   fully functional 1-to-1 operational copy of the Asian DVD Club server
#   from Google Drive backup streams.
# ==============================================================================

set -euo pipefail

RESTORE_STAGING_DIR="/tmp/adc-restore-ground-zero"
RCLONE_CONF="/opt/adc-backup/rclone.conf"
REMOTE_SOURCE="${1:-gdrive1_crypt:}"

echo "======================================================================"
echo "   Asian DVD Club Server — Ground-Zero Bare-Metal / Cloud Restoration  "
echo "======================================================================"
echo "Source Crypt Remote: ${REMOTE_SOURCE}"
echo "Staging Directory:   ${RESTORE_STAGING_DIR}"
echo "Target Host:         $(hostname) ($(uname -m))"
echo "Date:                $(date -u)"
echo "======================================================================"

if [ "$EUID" -ne 0 ]; then
  echo "[FATAL] Ground-zero restoration must be run as root." >&2
  exit 1
fi

mkdir -p "${RESTORE_STAGING_DIR}"

# ── STAGE 1: Download All Data Classes from Remote Crypt ─────────────────────
echo ""
echo "[STAGE 1/6] Downloading backup streams from ${REMOTE_SOURCE}..."
rclone copy "${REMOTE_SOURCE}" "${RESTORE_STAGING_DIR}" \
  --config "${RCLONE_CONF}" \
  --transfers 8 \
  --checkers 16 \
  --progress

# ── STAGE 2: Restore System Package Dependencies ──────────────────────────────
echo ""
echo "[STAGE 2/6] Restoring Linux APT packages & Python virtual environment..."
if [ -f "${RESTORE_STAGING_DIR}/packages/packages.list" ]; then
  apt-get update
  dpkg --set-selections < "${RESTORE_STAGING_DIR}/packages/packages.list"
  apt-get dselect-upgrade -y || true
fi

if [ -f "${RESTORE_STAGING_DIR}/packages/pip-requirements.txt" ]; then
  python3 -m pip install -r "${RESTORE_STAGING_DIR}/packages/pip-requirements.txt" || true
fi

# ── STAGE 3: Restore Core Codebase, Services & Scripts ────────────────────────
echo ""
echo "[STAGE 3/6] Restoring Asian DVD Club codebase, services & scripts..."
mkdir -p /var/www/html /opt/adc /home/solace /home/adc

if [ -d "${RESTORE_STAGING_DIR}/data/adc-website" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/data/adc-website/" /var/www/html/
fi

if [ -d "${RESTORE_STAGING_DIR}/data/opt-adc-app" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/data/opt-adc-app/" /opt/adc/
fi

if [ -d "${RESTORE_STAGING_DIR}/data/home-solace" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/data/home-solace/" /home/solace/
fi

if [ -d "${RESTORE_STAGING_DIR}/data/home-adc" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/data/home-adc/" /home/adc/
fi

# ── STAGE 4: Restore MySQL / MariaDB Database Dumps ───────────────────────────
echo ""
echo "[STAGE 4/6] Importing MySQL / MariaDB database dumps..."
LATEST_DUMP=$(ls -t "${RESTORE_STAGING_DIR}"/data/mysql-dumps/all-databases-*.sql.gz 2>/dev/null | head -1 || true)

if [ -n "${LATEST_DUMP}" ]; then
  echo "Found database dump: ${LATEST_DUMP}"
  systemctl start mariadb || systemctl start mysql || true
  zcat "${LATEST_DUMP}" | mysql || echo "[WARN] Database import returned warnings"
else
  echo "[WARN] No MySQL dump file found in backup stream."
fi

# ── STAGE 5: Restore System Configs, Cron, SSL Certs & Secrets ──────────────
echo ""
echo "[STAGE 5/6] Restoring /etc, crontabs, SSL certificates, and SSH keys..."
if [ -d "${RESTORE_STAGING_DIR}/config/etc-system" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/config/etc-system/" /etc/
fi

if [ -d "${RESTORE_STAGING_DIR}/config/cron-tabs" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/config/cron-tabs/" /var/spool/cron/crontabs/
fi

if [ -d "${RESTORE_STAGING_DIR}/secrets" ]; then
  rsync -avz "${RESTORE_STAGING_DIR}/secrets/" /
fi

# ── STAGE 6: Reload Systemd Services & Web Server ────────────────────────────
echo ""
echo "[STAGE 6/6] Reloading systemd services and restarting web servers..."
systemctl daemon-reload
systemctl restart apache2 || systemctl restart nginx || true
systemctl restart adc-backup || true

echo ""
echo "======================================================================"
echo "  ★ GROUND-ZERO RESTORATION COMPLETE! Asian DVD Club Server Restored.  "
echo "======================================================================"
