# Troubleshooting Guide

## 1. Introduction
If you are experiencing issues with CloudBackup for Windows, this guide covers the most common problems and their solutions. If your issue is not listed here, please check the GitHub Issues page.

## 2. Common Issues Quick Reference

| Issue | Potential Cause | Solution |
|---|---|---|
| Dashboard does not start | Port 8080 is already in use | Change dashboard port or stop conflicting service |
| Drive shows "Not Authorized" | Expired or revoked OAuth token | Re-authenticate the drive in the dashboard |
| Backup fails with network error | Intermittent internet connection | Retry backup; check firewall settings |
| Backup is slow | ISP throttling or large file processing | Run backups during off-peak hours |
| Drive capacity shows wrong values | Provider API lag or caching | Wait 24 hours or click "Refresh Stats" |
| OAuth window does not open | Default browser not set | Manually copy the auth URL into a browser |
| Scheduled task does not run | Incorrect Windows permissions | Update the task to "Run with highest privileges" |
| Cannot delete a cloud remote | Remote is locked by an active job | Cancel the active backup job first |
| `rclone` not found | Missing from system PATH | Re-run the installation script |
| Python not found | Python not installed or in PATH | Install Python and check "Add to PATH" |

## 3. Detailed Troubleshooting Steps

### a. Dashboard does not start / port 8080 already in use
By default, the dashboard runs on `http://localhost:8080`. If another application is using this port, CloudBackup will fail to start the web server.
**Solution:**
You can modify the `config.json` file to use a different port:
```json
{
  "dashboard_port": 8081
}
```
Restart the application after making this change.

### b. Drive shows "Not Authorized"
Cloud providers periodically expire OAuth tokens for security reasons.
**Solution:**
1. Open the dashboard.
2. Go to the **Drives** tab.
3. Click **Reconnect** next to the affected drive and follow the standard login prompts.

### c. Backup fails with network error
Temporary network drops can interrupt uploads.
**Solution:**
The backup engine handles retries automatically, but persistent failures may require you to check your Windows Firewall or third-party antivirus to ensure CloudBackup and `rclone` are allowed through.

### d. Backup is slow
Initial backups are always slower as every file must be processed and uploaded.
**Solution:**
- Leave the computer on overnight for the first backup.
- Subsequent incremental backups will be much faster.

### e. Drive capacity shows wrong values
Sometimes, cloud providers delay updating storage usage metrics via their APIs.
**Solution:**
This usually resolves itself within 24 hours. You can force a recount in the dashboard via the **Refresh Stats** button.

### f. OAuth window does not open
When adding a new drive, a browser window should appear.
**Solution:**
If it does not, check the terminal or log file. The authorization URL is always printed in plain text. Copy and paste it into your preferred web browser manually.

### g. Scheduled task does not run
The background backup relies on Windows Task Scheduler.
**Solution:**
1. Open Windows Task Scheduler.
2. Find `CloudBackupTask`.
3. Right-click -> **Properties**.
4. Check the box for **Run with highest privileges**.
5. Ensure **Run whether user is logged on or not** is selected.

### h. Cannot delete a cloud remote
You cannot remove a drive if it is currently being used for a backup or restore.
**Solution:**
Stop all running jobs in the dashboard, then try deleting the remote again.

### i. rclone not found
The application relies on `rclone.exe`.
**Solution:**
Ensure `rclone` is correctly installed. Rerun the setup script or manually place `rclone.exe` in the application directory.

### j. Python not found
CloudBackup requires Python.
**Solution:**
Download the latest version of Python for Windows. During installation, make sure you check the box labeled **Add Python to PATH**.

## 4. Checking Log Files
If you need more details, check the application logs.
Logs are located in the `logs/` directory inside the application folder.
- `app.log`: Contains dashboard and general application events.
- `backup.log`: Contains detailed output of backup runs and `rclone` operations.

## 5. Getting Help
If you have tried the steps above and are still having trouble, please search our GitHub Issues. 
If your issue is new, open a new issue with a clear description and attach relevant excerpts from your `app.log` (ensure no sensitive information is included).
