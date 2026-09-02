# CloudBackup for Windows — User Guide

This guide explains how to manage your encrypted cloud backups, monitor drive capacity, and perform restores using the local web dashboard.

---

## Accessing the Dashboard

Open your web browser and navigate to:
```text
http://127.0.0.1:8765
```

The web dashboard is restricted to your local machine by default (`127.0.0.1`) for security.

---

## Dashboard Overview

The top bar displays:
- **System Active Status**: Indicates whether automated jobs are enabled.
- **Active Drive**: Shows your active Google Drive account and storage capacity.
- **Quick Controls**:
  - `Run Backup`: Manually trigger an immediate backup pass.
  - `Dry Run`: Test backup rules without modifying any local or remote data.
  - `Pause / Resume`: Temporarily suspend or re-enable automatic schedules.
  - `Verify`: Check file integrity against cloud storage.
  - `Restore Test`: Run a dry-run restore to verify disaster readiness.

---

## Managing Cloud Remotes

CloudBackup supports multiple Google Drive accounts with automatic capacity fill monitoring:

- **Fill Thresholds**: Configure alerts when a drive reaches 90%, 95%, or 98% capacity.
- **Priority Re-ordering**: Drag or arrange remotes to specify which drive receives uploads first.
- **Re-authorization**: If Google OAuth tokens expire, click **Re-authorize** on the remote row to log in again.

---

## Backup vs Sync Semantics

- **Copy Mode (Default & Non-Destructive)**: Uploads new or updated files to the cloud. Existing files on the cloud are **never** deleted, even if you delete them from your local hard drive.
- **Sync Mode (Advanced)**: Mirrors your local folder to cloud storage. *Warning: Sync mode deletes remote files if they were deleted locally.* Sync mode is disabled by default and requires explicit two-step confirmation.

---

## Restoring Backed-Up Files

In the event of accidental file deletion or system loss:
1. Open the dashboard and click **Restore Test**.
2. Select the snapshot run from the **Snapshot History** table.
3. Click **Restore Files** and choose a staging location.
4. Verify your restored files before copying them back to your production directories.
