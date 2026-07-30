# CloudBackup for Windows Installation Guide

Welcome to the CloudBackup for Windows installation guide! This document will walk you through the entire process of setting up CloudBackup, from system requirements to scheduling your first automated backup. CloudBackup is a powerful, Python-based tool that encrypts and deduplicates your files before safely uploading them to cloud providers like Google Drive, OneDrive, and Microsoft Teams.

## System Requirements

| Item | Requirement |
|---|---|
| Operating System | Windows 10 or Windows 11 (64-bit) |
| Python | Version 3.10 or newer |
| rclone | Latest stable version for Windows |
| Disk Space | At least 200 MB for installation, plus extra for SQLite catalog and cache |
| RAM | 2 GB minimum (4 GB recommended) |

## Step 1 — Install Python 3.10 or newer

CloudBackup is written in Python, so you will need it installed on your system.

1. Go to the [Python Downloads Page](https://python.org/downloads/windows/).
2. Download the latest Python 3 installer for Windows.
3. Run the installer.

> [!IMPORTANT]
> During installation, make sure to check the box that says **"Add Python to PATH"** before clicking Install Now.

## Step 2 — Install rclone for Windows

We use `rclone` to handle the actual uploading of data to various cloud providers safely and efficiently.

1. Go to the [rclone Downloads Page](https://rclone.org/downloads/).
2. Download the Windows executable (usually a `.zip` file).
3. Extract the contents to a safe location, such as `C:\rclone\`.
4. Add the `C:\rclone\` directory to your Windows System PATH.

> [!TIP]
> If you are unsure how to add a folder to your System PATH in Windows, search for "Edit the system environment variables" in your Start Menu, click "Environment Variables", and edit the "Path" variable under "System variables".

## Step 3 — Download CloudBackup for Windows

Next, download the CloudBackup code to your computer. Open your Command Prompt (cmd) or PowerShell, navigate to where you want to install it (e.g., `C:\`), and clone the repository:

```cmd
cd C:\
git clone https://github.com/example/cloudbackup-windows.git
cd cloudbackup-windows
```

## Step 4 — Install Python dependencies

CloudBackup relies on several open-source Python libraries. Install them by running:

```cmd
pip install -r requirements.txt
```

> [!NOTE]
> If you prefer to keep your environment clean, you can create a virtual environment first by running `python -m venv venv` and activating it with `venv\Scripts\activate`.

## Step 5 — Run the setup wizard

Initialize the SQLite catalog and generate your secure AES-256 encryption keys by running the setup wizard:

```cmd
python setup.py
```

Follow the on-screen prompts to set your primary backup password. Do not lose this password, as it is required to restore your files!

## Step 6 — Configure cloud accounts

You need to tell CloudBackup where to store your encrypted files. You can add Google Drive, OneDrive, or Microsoft Teams.

For detailed instructions on setting up each provider, please refer to our [WALKTHROUGH.md](WALKTHROUGH.md) guide.

## Step 7 — Start the web dashboard

CloudBackup includes a user-friendly web interface. Start the web server with:

```cmd
python web_server.py
```

Open your web browser and navigate to `http://localhost:8080`. From here, you can view your backup sets, monitor progress, and manage settings.

## Step 8 — Schedule automated backups

To ensure your files are always protected, you should schedule CloudBackup to run automatically using Windows Task Scheduler.

1. Open **Task Scheduler** from the Windows Start Menu.
2. Click **Create Basic Task** in the right pane.
3. Name the task "CloudBackup Daily" and click Next.
4. Choose **Daily** as the trigger and click Next.
5. Set the time you want the backup to run (e.g., 2:00 AM) and click Next.
6. Choose **Start a program** and click Next.
7. In the **Program/script** box, enter `python`.
8. In the **Add arguments** box, enter `backup.py --all`.
9. In the **Start in** box, enter the path to your installation folder, such as `C:\cloudbackup-windows\`.
10. Click **Finish**.

## Verifying the installation

To verify that everything is working correctly, you can run a manual test backup from the command line:

```cmd
python backup.py --test
```

If the command completes without errors, and you can see a test entry in your web dashboard at `http://localhost:8080`, your installation is successful!

## Uninstallation

If you ever need to remove CloudBackup for Windows:

1. Delete the installation folder (e.g., `C:\cloudbackup-windows\`).
2. Remove the scheduled task from Windows Task Scheduler.
3. (Optional) Uninstall Python and remove rclone from your System PATH if you no longer need them for other projects.
4. Keep your encryption keys and the uploaded cloud data if you plan to restore files on another machine later.
