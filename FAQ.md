# CloudBackup for Windows — Frequently Asked Questions

### Q: Do I need administrator rights to use CloudBackup?
**A:** No. Administrator rights are required only during installation to copy files to `C:\Program Files\CloudBackup` and set up `C:\ProgramData\CloudBackup`. Daily backup operation and Web UI access run cleanly under standard user privileges.

### Q: Does CloudBackup delete my files on Google Drive if I delete them on my PC?
**A:** No! CloudBackup operates in non-destructive **Copy Mode** by default. Files deleted locally remain safe in your encrypted cloud storage.

### Q: Where are application data and database state stored?
**A:** All machine-wide database state, logs, configuration, and temporary staging files are stored under `C:\ProgramData\CloudBackup` (`config`, `state`, `logs`, `temp`). Binaries remain read-only in `C:\Program Files\CloudBackup`.

### Q: Can I recover my files if my computer crashes completely?
**A:** Yes. Download `CloudBackup-Setup.exe` on a fresh Windows system, re-authorize your Google Account, and click **Restore Test** or follow `BOOTSTRAP.txt`.

### Q: How does rclone binary discovery work?
**A:** CloudBackup uses a fail-closed trust policy. It uses the bundled `bin/rclone.exe` binary verified via SHA-256 hash. Implicit `PATH` lookups are prohibited to prevent binary hijacking.
