# CloudBackup for Windows — Nontechnical Installation Guide

Welcome to **CloudBackup for Windows**! This guide is designed for everyday users installing CloudBackup on Windows 10 or Windows 11.

---

## What CloudBackup Does

CloudBackup automatically encrypts and backs up your critical personal files, documents, and system configuration directly to your own Google Drive storage account.

- **Nontechnical Friendly**: Simple graphical setup wizard; no command line, Python, or technical knowledge required.
- **Zero-Knowledge Encryption**: Your files are encrypted on your PC *before* being uploaded. No one (not even Google) can read your data without your passphrase.
- **Local Dashboard**: Access your dashboard directly from your web browser at `http://127.0.0.1:8765`.

---

## System Requirements

- **Operating System**: Windows 10 or Windows 11 (64-bit).
- **Disk Space**: 100 MB available for application binaries and state database.
- **Account**: A free or paid Google Account with Google Drive storage.

---

## Step-by-Step Installation

### 1. Download the Installer
Download `CloudBackup-Setup.exe` from the official GitHub Releases page:
[https://github.com/koppot/cloudbackup-windows/releases](https://github.com/koppot/cloudbackup-windows/releases)

### 2. Run the Setup Wizard
Double-click `CloudBackup-Setup.exe` to launch the Windows Setup Wizard:
1. Accept the Windows User Account Control (UAC) prompt to allow installation into `C:\Program Files\CloudBackup`.
2. Click **Next** to proceed with default settings.
3. Select whether to create a Desktop shortcut.
4. Click **Install**.
5. Once installation finishes, check **Launch CloudBackup** and click **Finish**.

---

## First-Run Onboarding

When CloudBackup launches for the first time, your default web browser will open to:
```text
http://127.0.0.1:8765
```

### 1. Add Your First Data Source
- Under **Backup Sources**, select folders you want to safeguard (e.g. `C:\Users\YourName\Documents`).

### 2. Connect Google Drive
- Click **Setup Wizard / Add Remote**.
- A Google sign-in window will open in your browser. Log in and grant permission.
- CloudBackup will verify the connection automatically.

### 3. Run Your First Test Backup
- Click **Dry Run** to test your backup without uploading data.
- Once verified, click **Run Backup** to start your first encrypted backup.

---

## Daily Operation & Maintenance

- **Privilege Model**: Normal daily application use requires **NO administrative rights**.
- **Background Schedule**: Automatic backups are disabled by default. You can enable automatic backup schedules at any time from the Web UI under Settings.
- **Uninstallation**: To remove CloudBackup, open Windows **Settings > Apps > Installed apps**, locate **CloudBackup**, and click **Uninstall**.
  - Your backed-up data on Google Drive remains 100% safe and will **never** be deleted by the uninstaller.
