#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# ADC Backup System — Linux Installer
# ==============================================================================

echo "======================================================================"
echo "                ADC Backup System — Linux Installer                   "
echo "======================================================================"

# 1. Safety Check: Root permissions
if [ "${EUID}" -ne 0 ]; then
    echo "[ERROR] This installation script must be run as root (or via sudo)."
    exit 1
fi

# 2. Safety Check: Python 3.10+
if ! command -v python3 &>/dev/null; then
    echo "[ERROR] python3 is not installed. Please install Python 3.10 or higher."
    exit 1
fi

PYTHON_VERSION_OK=$(python3 -c "import sys; print(1 if sys.version_info >= (3, 10) else 0)")
if [ "${PYTHON_VERSION_OK}" -ne 1 ]; then
    echo "[ERROR] Python 3.10+ is required. Found Python version:"
    python3 --version
    exit 1
fi
echo "[OK] Python 3.10+ detected: $(python3 --version)"

# 3. Create target directory structure
INSTALL_DIR="/opt/adc-backup"
echo "[INFO] Creating target directory structure in ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"/{linux,shared,scripts,systemd,tests,logs,catalog_backups}

# 4. Copy project files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[INFO] Copying application files from ${SCRIPT_DIR} to ${INSTALL_DIR}..."
cp -R "${SCRIPT_DIR}"/* "${INSTALL_DIR}/"

# 5. Install Python dependencies
echo "[INFO] Installing Python dependencies..."
if [ -f "${INSTALL_DIR}/requirements.txt" ]; then
    python3 -m pip install --upgrade pip
    python3 -m pip install -r "${INSTALL_DIR}/requirements.txt"
else
    echo "[WARNING] ${INSTALL_DIR}/requirements.txt not found!"
fi

# 6. Check and install rclone if missing
if command -v rclone &>/dev/null; then
    echo "[OK] rclone is already installed: $(rclone version | head -n 1)"
else
    echo "[INFO] rclone not found. Installing official rclone binary..."
    if command -v curl &>/dev/null; then
        curl https://rclone.org/install.sh | bash
    else
        echo "[ERROR] 'curl' is required to install rclone automatically. Please install curl or rclone manually."
        exit 1
    fi
fi

# 7. Copy systemd unit file and enable service
SERVICE_SRC="${INSTALL_DIR}/systemd/adc-backup.service"
SERVICE_DEST="/etc/systemd/system/adc-backup.service"

if [ -f "${SERVICE_SRC}" ]; then
    echo "[INFO] Installing systemd unit file..."
    cp "${SERVICE_SRC}" "${SERVICE_DEST}"
    chmod 644 "${SERVICE_DEST}"
    systemctl daemon-reload
    systemctl enable adc-backup.service
    echo "[OK] adc-backup.service enabled (not started)."
else
    echo "[WARNING] Systemd service file not found at ${SERVICE_SRC}"
fi

# 8. Post-install instructions
echo "======================================================================"
echo "                  INSTALLATION COMPLETE                               "
echo "======================================================================"
echo "Next steps required before starting the service:"
echo ""
echo "  1. Copy configuration file:"
echo "     cp ${INSTALL_DIR}/config.yaml.example ${INSTALL_DIR}/config.yaml"
echo "     nano ${INSTALL_DIR}/config.yaml"
echo ""
echo "  2. Configure rclone Google Drive remotes & crypt:"
echo "     rclone config --config ${INSTALL_DIR}/rclone.conf"
echo ""
echo "  3. Generate TOTP secret and set admin password:"
echo "     python3 ${INSTALL_DIR}/scripts/generate_totp.py --auth-file ${INSTALL_DIR}/auth.json"
echo ""
echo "  4. Start the service when ready:"
echo "     systemctl start adc-backup.service"
echo "     systemctl status adc-backup.service"
echo "======================================================================"
