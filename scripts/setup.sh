#!/usr/bin/env bash
# setup.sh — One-shot installation script for ADC Backup System (Linux)
# Run as root on the target Linux host.

set -euo pipefail

INSTALL_DIR="/opt/adc-backup"
USER="adc-backup"
SERVICE="adc-backup"

echo "[setup] ADC Backup System installer"

# ── Create system user ──
if ! id "$USER" &>/dev/null; then
    useradd --system --no-create-home --shell /sbin/nologin "$USER"
    echo "[setup] Created system user: $USER"
fi

# ── Create directory structure ──
mkdir -p "$INSTALL_DIR"/{db,logs,dumps,packages,config,profiles}
chown -R "$USER:$USER" "$INSTALL_DIR"
chmod 750 "$INSTALL_DIR"

# ── Copy application files ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_SRC="$(dirname "$SCRIPT_DIR")"

rsync -av --exclude='__pycache__' --exclude='*.pyc' --exclude='.git' \
    "$APP_SRC/" "$INSTALL_DIR/"

chown -R "$USER:$USER" "$INSTALL_DIR"

# ── Create rclone config dir ──
mkdir -p "$INSTALL_DIR"
touch "$INSTALL_DIR/rclone.conf"
chmod 600 "$INSTALL_DIR/rclone.conf"
chown "$USER:$USER" "$INSTALL_DIR/rclone.conf"

# ── Python virtual environment ──
if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
    echo "[setup] Virtual environment created"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
echo "[setup] Python dependencies installed"

# ── .env from example if not present ──
if [ ! -f "$INSTALL_DIR/config/.env" ]; then
    cp "$INSTALL_DIR/config/.env.example" "$INSTALL_DIR/config/.env"
    chmod 600 "$INSTALL_DIR/config/.env"
    chown "$USER:$USER" "$INSTALL_DIR/config/.env"
    echo "[setup] Created config/.env from example. Edit before starting."
fi

# ── Initialise SQLite database ──
sudo -u "$USER" "$INSTALL_DIR/venv/bin/python" -c "
import sys; sys.path.insert(0, '$INSTALL_DIR')
from shared.database import init_db
init_db('$INSTALL_DIR/db/state.db')
print('[setup] Database initialised')
"

# ── Set admin password ──
echo
echo "[setup] Set admin password:"
read -s -r -p "Password: " PW
echo
HASH=$("$INSTALL_DIR/venv/bin/python" -c "
import bcrypt, sys
print(bcrypt.hashpw(sys.argv[1].encode(), bcrypt.gensalt()).decode())
" "$PW")

# Write hash to .env
if grep -q "ADMIN_PASSWORD_HASH" "$INSTALL_DIR/config/.env"; then
    sed -i "s|^ADMIN_PASSWORD_HASH=.*|ADMIN_PASSWORD_HASH=$HASH|" "$INSTALL_DIR/config/.env"
else
    echo "ADMIN_PASSWORD_HASH=$HASH" >> "$INSTALL_DIR/config/.env"
fi
echo "[setup] Admin password set."

# ── Systemd service ──
cp "$INSTALL_DIR/systemd/adc-backup.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable adc-backup
echo "[setup] systemd service enabled: adc-backup"

echo
echo "[setup] Installation complete."
echo "[setup] Edit $INSTALL_DIR/config/.env before starting."
echo "[setup] Then run: systemctl start adc-backup"
echo "[setup] Web UI will be available on the Tailscale IP at port 8080."
