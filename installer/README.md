# CloudBackup for Windows Installer Build Guide

This directory contains the Inno Setup compiler script (`CloudBackupInstaller.iss`) used to generate the standalone Windows installer `CloudBackup-Setup.exe`.

## Prerequisites

1. **Inno Setup 6.x** installed (available via `choco install innosetup` or from [jrsoftware.org](https://www.jrsoftware.org/isdl.php)).
2. Built PyInstaller distribution located in `dist/CloudBackup/`.

## Build Instructions

1. Build the PyInstaller standalone executable package:
   ```cmd
   pyinstaller CloudBackup.spec
   ```

2. Compile the installer executable:
   ```cmd
   iscc installer/CloudBackupInstaller.iss
   ```

3. The generated installer will be located at:
   ```text
   dist/CloudBackup-Setup.exe
   ```

## Directory Permissions & Privilege Rationale

- **Executable Installation**: `{autopf}\CloudBackup` (`C:\Program Files\CloudBackup`). Read-only for standard users to prevent tampering.
- **Machine Data Directory**: `{commonappdata}\CloudBackup` (`C:\ProgramData\CloudBackup`).
- **Subdirectories**: `config`, `state`, `logs`, `temp` created with isolated ACL permissions.
- **Elevation Requirement**: Administrator privileges are required during installation to write to `Program Files` and `ProgramData`. Normal daily execution after installation requires NO administrator rights.
