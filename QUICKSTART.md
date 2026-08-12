# CloudBackup for Windows Quickstart

Get up and running with CloudBackup for Windows in just 5 minutes! This guide assumes you already have Python 3.10+ and `rclone` installed on your system.

## 1. Clone the repo

Open your Command Prompt or PowerShell, navigate to your preferred directory, and download the project:

```cmd
git clone https://github.com/example/cloudbackup-windows.git
cd cloudbackup-windows
```

## 2. Install dependencies

Install the required Python packages:

```cmd
pip install -r requirements.txt

```


## 3. Start the dashboard

Launch the local web dashboard so you can manage your backups easily:

```cmd
python web_server.py
```

Open your web browser and go to `http://localhost:8080`.

## 4. Add your first cloud drive target

In the web dashboard, navigate to the **Destinations** tab and click **Add New Destination**. Follow the prompts to connect your Google Drive, OneDrive, or Microsoft Teams account.

![Wizard](docs/screenshots/add-remote-wizard.jpg)

## 5. Run your first backup

You can start a backup directly from the dashboard, or by running this command in a new terminal window:

```cmd
python backup.py --start
```

## 6. Check backup status

Head back to the web dashboard at `http://localhost:8080`. The **Dashboard** homepage will display the progress of your current backup, including upload speed and the amount of data deduplicated.

## 7. What happens next

Once your initial backup is complete, CloudBackup is ready for daily use. For hands-off protection, we recommend setting up a Windows Scheduled Task to run `python backup.py --all` automatically in the background. Check our full documentation for scheduling instructions!
