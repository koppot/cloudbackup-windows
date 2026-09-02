# CloudBackup for Windows — Troubleshooting Guide

This guide helps resolve common issues encountered during setup or backup runs.

---

## Common Issues & Resolutions

### 1. Web UI Dashboard Won't Load (`http://127.0.0.1:8765`)
- **Cause**: Another service is using port 8765 or the server instance crashed.
- **Fix**: Check `C:\ProgramData\CloudBackup\logs\` for recent log entries. Launch `CloudBackup.exe --port 8766` to use an alternate port.

### 2. Google OAuth Token Expired / Authentication Error
- **Cause**: Google OAuth access tokens expire periodically.
- **Fix**: Open Web UI dashboard, click **Re-authorize** on the Google Drive remote row, and complete the browser sign-in flow.

### 3. Source Path Error: "Invalid Source Path"
- **Cause**: The input path contains invalid Windows characters, reserved device names (`CON`, `PRN`, `NUL`), or attempted directory traversal outside allowed roots.
- **Fix**: Ensure source path is an absolute Windows folder path (e.g. `C:\Users\YourName\Documents`).

### 4. rclone Binary Not Found
- **Cause**: The bundled `rclone.exe` binary is missing or modified.
- **Fix**: Re-run `CloudBackup-Setup.exe` to repair the installation files under `C:\Program Files\CloudBackup`.
