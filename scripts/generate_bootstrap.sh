#!/usr/bin/env bash
# generate_bootstrap.sh — Write BOOTSTRAP.txt to the unencrypted root of gdrive1:
# This file is plain text, readable before any crypt passphrase is available.
# Run as the adc-backup user.

set -euo pipefail

INSTALL_DIR="/opt/adc-backup"
REMOTE="gdrive1"   # Edit to match your first Drive remote name
RCLONE="$INSTALL_DIR/venv/bin/rclone"
RCLONE_CONF="$INSTALL_DIR/rclone.conf"
HOSTNAME="$(hostname -f)"
DATE="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"

BOOTSTRAP_FILE="/tmp/adc-BOOTSTRAP.txt"

cat > "$BOOTSTRAP_FILE" << EOF
================================================================================
  ADC BACKUP SYSTEM — BOOTSTRAP RECOVERY FILE
  Host: $HOSTNAME
  Generated: $DATE
  WARNING: This file is UNENCRYPTED. Do not store secrets here.
================================================================================

This file exists in plain text at the root of the Google Drive account.
Read it before any other recovery step if you are rebuilding from scratch.

── STAGE 0: Prerequisites ──────────────────────────────────────────────────────
1. Install a fresh OS (Ubuntu 22.04 LTS or equivalent).
2. Run: curl https://rclone.org/install.sh | sudo bash
3. Connect to Tailscale: curl -fsSL https://tailscale.com/install.sh | sh
   Then: sudo tailscale up
4. Retrieve from password manager:
   - Data crypt passphrase (for gdrive1_crypt)
   - Secrets crypt passphrase (for gdrive1_secrets_crypt)
   - Google account credentials for OAuth re-auth

── STAGE 1: Authorize rclone ────────────────────────────────────────────────
5. Run: rclone config
   Add: gdrive1        (type=drive, browser OAuth)
   Add: gdrive1_crypt  (type=crypt, remote=gdrive1:backup, DATA passphrase)
   Add: gdrive1_secrets_crypt (type=crypt, remote=gdrive1:secrets, SECRETS passphrase)
6. Verify: rclone ls gdrive1_crypt:$HOSTNAME/packages/

── STAGE 2: Restore packages ───────────────────────────────────────────────
7.  rclone copy gdrive1_crypt:$HOSTNAME/packages/ /tmp/restore/packages/
8.  dpkg --set-selections < /tmp/restore/packages/packages.list
9.  apt-get dselect-upgrade -y
10. pip install -r /tmp/restore/packages/pip-requirements.txt

── STAGE 3: Restore config ─────────────────────────────────────────────────
11. rclone copy gdrive1_crypt:$HOSTNAME/config/etc/ /etc/
12. rclone copy gdrive1_crypt:$HOSTNAME/config/opt/ /opt/
    (DO NOT start services yet)

── STAGE 4: Restore database ───────────────────────────────────────────────
13. rclone copy gdrive1_crypt:$HOSTNAME/data/ /tmp/restore/data/
14. mysql -u root < /tmp/restore/data/all-databases-*.sql.gz  (gunzip first if needed)

── STAGE 5: Restore secrets ───────────────────────────────────────────────
15. rclone copy gdrive1_secrets_crypt:$HOSTNAME/secrets/ /tmp/restore/secrets/
16. cp -r /tmp/restore/secrets/etc/ssl /etc/ssl
    cp -r /tmp/restore/secrets/root/.ssh /root/.ssh
    cp -r /tmp/restore/secrets/opt/adc/secrets /opt/adc/secrets
    chmod 700 /root/.ssh && chmod 600 /root/.ssh/*

── STAGE 6: Start services ─────────────────────────────────────────────────
17. systemctl daemon-reload
18. systemctl enable --now adc-backup
19. Verify services are running.

── STAGE 7: Re-authorize Google Drive remotes ────────────────────────────
20. Open the ADC Backup UI (Tailscale IP:8080).
21. Log in with your password and TOTP.
22. Go to Drives → Re-authorize each remote.
23. Run a test backup from Jobs → Run Now to confirm round-trip.

================================================================================
For assistance: see the full runbook in /opt/adc-backup/docs/restore-runbook.md
================================================================================
EOF

echo "[bootstrap] Writing BOOTSTRAP.txt to $REMOTE: root..."
"$RCLONE" copy "$BOOTSTRAP_FILE" "$REMOTE:" --config "$RCLONE_CONF"
echo "[bootstrap] Done. BOOTSTRAP.txt is now at the unencrypted root of $REMOTE:"
echo "[bootstrap] Verify: $RCLONE ls $REMOTE: --config $RCLONE_CONF"
