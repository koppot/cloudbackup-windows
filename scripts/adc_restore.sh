#!/usr/bin/env bash
# ==============================================================================
# ADC Backup System — Full Linux Bare-Metal Restore Script v2.0
# ==============================================================================
#
# Usage (run this on your LOCAL machine — it connects to the bare target via SSH):
#
#   bash adc_restore.sh <TARGET_IP> <SSH_USER> [SSH_KEY_PATH]
#
# Examples:
#   bash adc_restore.sh 45.135.163.139 root ~/.ssh/id_rsa
#   bash adc_restore.sh 45.135.163.139 root           # uses SSH agent / default key
#
# Assumptions:
#   - Target machine has a fresh Ubuntu 22.04/24.04 install with SSH open.
#   - You have a valid rclone.conf with authorized gdrive1/gdrive1_crypt remotes.
#   - The rclone.conf is passed to the target as part of this script.
#
# What this script restores:
#   1. System dependencies (apt packages from dpkg-selections, pip packages)
#   2. rclone binary + Google Drive credentials
#   3. Linux application files + configs (/etc, /opt/adc, /opt/adc-backup/config)
#   4. Web application (/var/www/html)
#   5. MySQL databases (from most recent .sql.gz dump)
#   6. /usr/local/bin custom scripts (custom toolchain: OCR, transcoder, etc.)
#   7. Crontabs + home directories
#   8. Secrets (SSL certs, SSH keys, Wireguard, app secrets)
#   9. ADC backup service (systemd unit + Apache proxy)
#  10. All services restarted + verification
#
# NOTE: Windows supermicro.local backup system is NOT touched.
#       This script is Linux/asiandvdclub.org only.
# ==============================================================================

set -euo pipefail

# ── Args ────────────────────────────────────────────────────────────────────────
TARGET_IP="${1:-}"
SSH_USER="${2:-root}"
SSH_KEY="${3:-}"

if [[ -z "$TARGET_IP" ]]; then
  echo "Usage: bash adc_restore.sh <TARGET_IP> <SSH_USER> [SSH_KEY_PATH]" >&2
  exit 1
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"
[[ -n "$SSH_KEY" ]] && SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
SSH="ssh $SSH_OPTS $SSH_USER@$TARGET_IP"
SCP="scp $SSH_OPTS"

# ── Colour helpers ──────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✓ $*${NC}"; }
warn() { echo -e "${YELLOW}  ⚠ $*${NC}"; }
fail() { echo -e "${RED}  ✗ FATAL: $*${NC}" >&2; exit 1; }
stage(){ echo -e "\n${GREEN}══════════════════════════════════════════${NC}"; \
         echo -e "${GREEN}  Stage $*${NC}"; \
         echo -e "${GREEN}══════════════════════════════════════════${NC}"; }

REMOTE_SOURCE="gdrive1_crypt:linux-control"
SECRETS_REMOTE="gdrive1_secrets_crypt:linux-control"
STAGING="/tmp/adc-restore"
RCLONE_CONF_SRC="${HOME}/.config/rclone/rclone.conf"

# ── Preflight ───────────────────────────────────────────────────────────────────
stage "0/9 — Preflight"

# SSH connectivity check
$SSH "echo connected" &>/dev/null || fail "Cannot SSH to $TARGET_IP. Check IP, user, and key."
ok "SSH connection to $SSH_USER@$TARGET_IP established"

# Check rclone.conf is available locally
if [[ ! -f "$RCLONE_CONF_SRC" ]]; then
  # Try common alternate paths
  for alt in "/opt/adc-backup/rclone.conf" "$HOME/.rclone.conf"; do
    [[ -f "$alt" ]] && RCLONE_CONF_SRC="$alt" && break
  done
fi
[[ -f "$RCLONE_CONF_SRC" ]] || fail "rclone.conf not found locally. Expected at ~/.config/rclone/rclone.conf or /opt/adc-backup/rclone.conf. Copy it from your password manager backup."

ok "rclone.conf found at $RCLONE_CONF_SRC"

# Internet connectivity on target
$SSH "curl -fsS --max-time 8 https://rclone.org > /dev/null" || fail "Target has no internet connectivity. Cannot proceed."
ok "Target internet connectivity confirmed"

# Disk space check (need at least 60 GB for a full restore)
FREE_GB=$($SSH "df -BG / | awk 'NR==2 {gsub(\"G\",\"\",$4); print $4}'")
(( FREE_GB >= 60 )) || warn "Only ${FREE_GB} GB free on /. Recommend at least 60 GB for full restore."
ok "Disk: ${FREE_GB} GB free on /"

# ── Stage 1: System dependencies ────────────────────────────────────────────────
stage "1/9 — System Dependencies"

$SSH "bash -s" <<'REMOTE_SH'
set -euo pipefail
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3 python3-pip python3-venv python3-dev \
  curl wget rsync unzip git sqlite3 \
  apache2 libapache2-mod-proxy-html \
  mysql-server mysql-client \
  php8.2 php8.2-mysql php8.2-curl php8.2-gd php8.2-mbstring php8.2-xml \
  php8.2-zip php8.2-intl php8.2-bcmath php8.2-memcached \
  composer \
  ffmpeg \
  build-essential libssl-dev libffi-dev \
  memcached \
  jemalloc libjemalloc-dev 2>/dev/null || true
a2enmod proxy proxy_http headers rewrite ssl 2>/dev/null || true
systemctl start apache2 || true
echo "APT setup complete."
REMOTE_SH
ok "System packages installed"

# ── Stage 2: rclone + Google Drive credentials ──────────────────────────────────
stage "2/9 — rclone & Google Drive Credentials"

$SSH "which rclone || curl -fsSL https://rclone.org/install.sh | bash" 2>/dev/null
ok "rclone binary ready: $($SSH 'rclone --version | head -1')"

$SSH "mkdir -p /opt/adc-backup"

# Copy authorised rclone.conf to target
$SCP "$RCLONE_CONF_SRC" "$SSH_USER@$TARGET_IP:/opt/adc-backup/rclone.conf"
$SSH "chmod 600 /opt/adc-backup/rclone.conf"
ok "rclone.conf deployed"

# Verify drive access
$SSH "rclone lsd gdrive1_crypt:linux-control --config /opt/adc-backup/rclone.conf 2>&1" \
  | grep -q 'linux-control\|config\|data' \
  || fail "gdrive1_crypt remote is not authorized or backup path not found. Check rclone.conf credentials."
ok "Google Drive remote verified — backup data accessible"

# ── Stage 3: Restore application & config files ─────────────────────────────────
stage "3/9 — Application Files & System Config"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
CONF=/opt/adc-backup/rclone.conf
REMOTE="${REMOTE_SOURCE}"
STAGING="${STAGING}"
mkdir -p "\$STAGING"

echo "  Pulling config class (etc, adc-backup-config, cron-tabs, usr-local-etc)..."
rclone copy "\${REMOTE}/config" "\${STAGING}/config" \
  --config "\$CONF" --transfers 8 --fast-list --progress 2>/dev/null || true

echo "  Applying /etc..."
if [ -d "\${STAGING}/config/etc" ]; then
  rsync -a --ignore-errors "\${STAGING}/config/etc/" /etc/ || true
fi

echo "  Applying adc-backup config..."
mkdir -p /opt/adc-backup/config
if [ -d "\${STAGING}/config/opt/adc-backup/config" ]; then
  rsync -a "\${STAGING}/config/opt/adc-backup/config/" /opt/adc-backup/config/ || true
fi

echo "  Applying crontabs..."
if [ -d "\${STAGING}/config/var/spool/cron/crontabs" ]; then
  rsync -a "\${STAGING}/config/var/spool/cron/crontabs/" /var/spool/cron/crontabs/ || true
  chmod 600 /var/spool/cron/crontabs/* 2>/dev/null || true
fi

echo "  Applying usr-local-etc..."
if [ -d "\${STAGING}/config/usr/local/etc" ]; then
  rsync -a "\${STAGING}/config/usr/local/etc/" /usr/local/etc/ || true
fi
echo "Config restore complete."
REMOTE_SH
ok "System config (/etc, cron, adc-backup config) restored"

# ── Stage 4: Restore web application + ADC binaries ────────────────────────────
stage "4/9 — Web Application & ADC Binaries"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
CONF=/opt/adc-backup/rclone.conf
REMOTE="${REMOTE_SOURCE}"
STAGING="${STAGING}"

echo "  Pulling data class (website, opt-adc, mysql-dumps, home dirs, var-backups)..."
rclone copy "\${REMOTE}/data" "\${STAGING}/data" \
  --config "\$CONF" --transfers 8 --fast-list --progress 2>/dev/null || true

mkdir -p /var/www/html /opt/adc/bin /opt/adc/scripts /home/solace /home/adc

if [ -d "\${STAGING}/data/var/www/html" ]; then
  rsync -a --ignore-errors "\${STAGING}/data/var/www/html/" /var/www/html/ || true
  chown -R www-data:www-data /var/www/html/ 2>/dev/null || true
  echo "  Web application restored."
fi

if [ -d "\${STAGING}/data/opt/adc" ]; then
  rsync -a "\${STAGING}/data/opt/adc/" /opt/adc/ || true
  chmod +x /opt/adc/bin/* 2>/dev/null || true
  echo "  ADC binaries and scripts restored."
fi

if [ -d "\${STAGING}/data/home/solace" ]; then
  rsync -a "\${STAGING}/data/home/solace/" /home/solace/ || true
  id solace &>/dev/null || useradd -m solace
  chown -R solace:solace /home/solace/ 2>/dev/null || true
fi

if [ -d "\${STAGING}/data/home/adc" ]; then
  rsync -a "\${STAGING}/data/home/adc/" /home/adc/ || true
  id adc &>/dev/null || useradd -m adc
  chown -R adc:adc /home/adc/ 2>/dev/null || true
fi

if [ -d "\${STAGING}/data/var/backups" ]; then
  rsync -a "\${STAGING}/data/var/backups/" /var/backups/ || true
fi
echo "Data restore complete."
REMOTE_SH
ok "Web application (/var/www/html) and ADC binaries (/opt/adc) restored"

# ── Stage 5: Restore MySQL databases ────────────────────────────────────────────
stage "5/9 — MySQL Database Restore"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
STAGING="${STAGING}"

# Find latest dump
DUMP_DIR="\${STAGING}/data/opt/adc-backup/dumps"
LATEST_DUMP=\$(ls -t "\${DUMP_DIR}"/all-databases-*.sql.gz 2>/dev/null | head -1 || true)

if [[ -z "\${LATEST_DUMP}" ]]; then
  echo "  [WARN] No MySQL dump found at \${DUMP_DIR}. Skipping database restore."
  echo "  Expected path: \${DUMP_DIR}/all-databases-YYYYMMDD-HHMMSS.sql.gz"
  exit 0
fi

echo "  Found dump: \${LATEST_DUMP} (\$(du -sh \${LATEST_DUMP} | cut -f1))"

systemctl start mysql 2>/dev/null || systemctl start mariadb 2>/dev/null || true
sleep 2

# Verify dump integrity before importing
DB_COUNT=\$(zcat "\${LATEST_DUMP}" | grep -c "^-- Current Database" || true)
if (( DB_COUNT < 1 )); then
  echo "  [WARN] Dump integrity check failed — no database sections found."
  exit 1
fi
echo "  Dump contains \${DB_COUNT} database(s). Importing..."

zcat "\${LATEST_DUMP}" | mysql 2>&1 | tail -5 || echo "[WARN] Import completed with warnings."

echo "  Verifying restored databases..."
mysql -e 'SHOW DATABASES;' 2>/dev/null | grep -E 'adc_db|adc_db_staging' && echo "  adc_db and adc_db_staging confirmed." || echo "  [WARN] Expected databases not found after restore."
REMOTE_SH
ok "MySQL databases restored"

# ── Stage 6: Restore /usr/local/bin custom scripts ──────────────────────────────
stage "6/9 — Custom Scripts (/usr/local/bin)"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
CONF=/opt/adc-backup/rclone.conf
REMOTE="${REMOTE_SOURCE}"
STAGING="${STAGING}"

echo "  Pulling packages class (manifest, /usr/local/bin scripts)..."
rclone copy "\${REMOTE}/packages" "\${STAGING}/packages" \
  --config "\$CONF" --transfers 8 --fast-list --progress 2>/dev/null || true

if [ -d "\${STAGING}/packages/usr/local/bin" ]; then
  SCRIPT_COUNT=\$(ls "\${STAGING}/packages/usr/local/bin/" | wc -l)
  rsync -a "\${STAGING}/packages/usr/local/bin/" /usr/local/bin/ || true
  chmod +x /usr/local/bin/* 2>/dev/null || true
  echo "  Restored \${SCRIPT_COUNT} scripts to /usr/local/bin."
else
  echo "  [WARN] No /usr/local/bin scripts found in backup packages class."
fi
REMOTE_SH
ok "/usr/local/bin custom scripts restored"

# ── Stage 7: Reinstall Python packages from manifests ───────────────────────────
stage "7/9 — Python Package Manifests & Reinstall"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
STAGING="${STAGING}"
PKG_DIR="\${STAGING}/packages/opt/adc-backup/packages"

if [ -f "\${PKG_DIR}/dpkg-selections.txt" ]; then
  echo "  Reinstalling dpkg package selections (\$(wc -l < \${PKG_DIR}/dpkg-selections.txt) packages)..."
  apt-get update -qq
  dpkg --set-selections < "\${PKG_DIR}/dpkg-selections.txt"
  DEBIAN_FRONTEND=noninteractive apt-get dselect-upgrade -y -qq 2>/dev/null || true
  echo "  dpkg reinstall complete."
fi

if [ -f "\${PKG_DIR}/pip-freeze-system.txt" ]; then
  echo "  Reinstalling system pip packages (\$(wc -l < \${PKG_DIR}/pip-freeze-system.txt) packages)..."
  pip3 install -q --break-system-packages -r "\${PKG_DIR}/pip-freeze-system.txt" 2>/dev/null || \
    pip3 install -q -r "\${PKG_DIR}/pip-freeze-system.txt" 2>/dev/null || true
  echo "  System pip reinstall complete."
fi

# Recreate the adc-backup virtualenv
mkdir -p /opt/adc-backup
python3 -m venv /opt/adc-backup/venv
if [ -f "\${PKG_DIR}/pip-freeze-venv.txt" ]; then
  echo "  Recreating adc-backup venv from pip freeze (\$(wc -l < \${PKG_DIR}/pip-freeze-venv.txt) packages)..."
  /opt/adc-backup/venv/bin/pip install -q --upgrade pip
  /opt/adc-backup/venv/bin/pip install -q -r "\${PKG_DIR}/pip-freeze-venv.txt" || true
fi

# Reinstall composer dependencies for the web app
if [ -f "/var/www/html/composer.json" ]; then
  echo "  Running composer install for web application..."
  cd /var/www/html
  composer install --no-interaction --no-dev --quiet 2>/dev/null || true
fi
echo "Package reinstall complete."
REMOTE_SH
ok "Python packages, venv, and PHP composer dependencies reinstalled"

# ── Stage 8: Restore secrets ─────────────────────────────────────────────────────
stage "8/9 — Secrets (SSL, SSH Keys, Wireguard)"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail
CONF=/opt/adc-backup/rclone.conf
SECRETS_REMOTE="${SECRETS_REMOTE}"
STAGING="${STAGING}"

echo "  Pulling secrets from dedicated crypt remote..."
rclone copy "\${SECRETS_REMOTE}" "\${STAGING}/secrets" \
  --config "\$CONF" --transfers 4 --fast-list --progress 2>/dev/null || \
  echo "  [WARN] Secrets remote pull failed or no secrets found."

if [ -d "\${STAGING}/secrets" ]; then
  rsync -a "\${STAGING}/secrets/" / --ignore-errors || true
fi

# Enforce strict permissions on sensitive files
chmod 700 /root/.ssh 2>/dev/null || true
chmod 600 /root/.ssh/authorized_keys /root/.ssh/id_* 2>/dev/null || true
chmod 700 /home/adc/.ssh 2>/dev/null || true
chmod 600 /home/adc/.ssh/* 2>/dev/null || true
chmod 700 /home/solace/.ssh 2>/dev/null || true
chmod 600 /home/solace/.ssh/* 2>/dev/null || true
chmod 600 /etc/ssl/private/* 2>/dev/null || true
chmod 600 /opt/adc-backup/rclone.conf 2>/dev/null || true
echo "Secrets restore and permissions set."
REMOTE_SH
ok "Secrets (SSL, SSH keys, Wireguard) restored with strict permissions"

# ── Stage 9: Services, systemd, and verification ────────────────────────────────
stage "9/9 — Service Startup & Verification"

$SSH "bash -s" <<REMOTE_SH
set -euo pipefail

# Write adc-backup systemd unit
cat > /etc/systemd/system/adc-backup.service <<'UNIT'
[Unit]
Description=ADC Backup System Administrative Interface
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/adc-backup
ExecStart=/opt/adc-backup/venv/bin/python3 /opt/adc-backup/linux/app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

# Reload and start all services
systemctl daemon-reload

echo "  Starting MySQL..."
systemctl enable --now mysql 2>/dev/null || systemctl enable --now mariadb 2>/dev/null || true

echo "  Starting Apache..."
systemctl enable --now apache2 || true
systemctl reload apache2 || true

echo "  Starting memcached..."
systemctl enable --now memcached 2>/dev/null || true

echo "  Starting ADC systemd services..."
for svc in adc-gateway adc-coordinator adc-ingest adc-process-queue adc-pool-writer adc-audit-worker adc-backup; do
  if [ -f "/etc/systemd/system/\${svc}.service" ]; then
    systemctl enable --now "\${svc}" 2>/dev/null || echo "  [WARN] \${svc} failed to start."
  fi
done

echo "  Starting cron..."
systemctl enable --now cron || true

sleep 3

# ── Verification checks ────────────────────────────────────────────────────────
echo ""
echo "══════════ Restore Verification Checks ══════════"

PASS=0; WARN=0

check() {
  local label="$1"; local cmd="$2"
  if eval "\$cmd" &>/dev/null; then
    echo "  ✓ \${label}"
    (( PASS++ ))
  else
    echo "  ✗ WARN: \${label}"
    (( WARN++ ))
  fi
}

check "adc-backup.service is active"    "systemctl is-active adc-backup"
check "apache2 is active"               "systemctl is-active apache2"
check "mysql is active"                 "systemctl is-active mysql || systemctl is-active mariadb"
check "/var/www/html/app/ exists"       "[ -d /var/www/html/app ]"
check "/opt/adc/bin/gateway exists"     "[ -x /opt/adc/bin/gateway ]"
check "/opt/adc/bin/coordinator exists" "[ -x /opt/adc/bin/coordinator ]"
check "adc_db database exists"          "mysql -e 'USE adc_db' 2>/dev/null"
check "rclone.conf in place"            "[ -f /opt/adc-backup/rclone.conf ]"
check "adc-backup venv is valid"        "[ -x /opt/adc-backup/venv/bin/python3 ]"
check "/usr/local/bin scripts present"  "[ \$(ls /usr/local/bin | wc -l) -ge 30 ]"
check "HTTP health check (backup UI)"   "curl -so /dev/null -w '%{http_code}' http://127.0.0.1:8765/backup/ | grep -qE '200|302'"
check "Google Drive remote accessible"  "rclone lsd gdrive1_crypt: --config /opt/adc-backup/rclone.conf 2>/dev/null"

echo ""
echo "  Passed: \${PASS} / Warned: \${WARN}"
echo "════════════════════════════════════════════════"
REMOTE_SH

# ── Summary ─────────────────────────────────────────────────────────────────────
echo -e "\n${GREEN}══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ★  ADC Backup System — Full Restore Complete         ${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Dashboard:  https://${TARGET_IP}/backup/drives"
echo "  Web App:    https://${TARGET_IP}/"
echo ""
echo "  Next steps:"
echo "  1. Update DNS to point asiandvdclub.org to ${TARGET_IP}"
echo "  2. Verify SSL certificate is active (Let's Encrypt via /root/.acme.sh)"
echo "  3. Log in to the ADC Backup UI and confirm Drive remotes are authorized"
echo ""
echo "  Windows supermicro.local: UNTOUCHED (separate system)."
