# Frequently Asked Questions (FAQ)

## General Information

### What is CloudBackup for Windows?
CloudBackup for Windows is an open-source, automated backup application designed specifically for Windows environments. It securely encrypts and uploads your files to various cloud storage providers with built-in deduplication and multi-drive rotation.

### Is it free?
Yes! CloudBackup for Windows is 100% free and open-source software. You only pay for the cloud storage you use with your respective providers.

### Does it work on Windows 10 and 11?
Yes, it is fully compatible with both Windows 10 and Windows 11.

### Does it work on Windows Server?
Yes, it supports recent versions of Windows Server, though it is primarily designed with consumer and prosumer environments in mind.

## Cloud Storage & Providers

### What cloud providers are supported?
Currently, CloudBackup supports Google Drive, Microsoft OneDrive, and Microsoft Teams SharePoint. 

### What happens if I delete a cloud drive account?
If a cloud account is deleted or disabled by the provider, CloudBackup will not be able to upload or retrieve files from that specific drive. The data on other drives remains unaffected.

### Can I restore files from a removed drive?
No, if a drive is completely removed from the cloud provider, the data is gone. If you simply remove it from the CloudBackup dashboard, the data remains in the cloud, but you must re-add the drive to access it via the application.

## Encryption & Security

### How is encryption handled?
All data is encrypted client-side using AES-256 via `rclone crypt` before it ever leaves your computer. The cloud providers only receive encrypted blobs.

### Where is the encryption key stored?
The encryption key and salt are stored securely on your local machine. They are never uploaded to the cloud or transmitted to any third-party servers.

### Is my data safe in the cloud?
Yes, because we use zero-knowledge, client-side encryption, your cloud provider cannot read your files. Your data is safe even in the event of a cloud provider data breach, provided your local encryption keys are secure.

## Features & Operations

### How does deduplication work?
CloudBackup checks if a file has already been uploaded. If it detects an identical file (based on its hash), it creates a reference rather than uploading the file again. This saves bandwidth and cloud storage space.

### How does drive rotation work?
The application distributes backups across multiple configured cloud drives. This provides redundancy and balances storage usage across multiple accounts or providers.

### How do I add more drives later?
You can easily add new cloud drives at any time via the web dashboard. CloudBackup will automatically incorporate them into future backup jobs.

### What is the fill threshold?
The fill threshold dictates how much free space must be remaining on a cloud drive before CloudBackup stops uploading new files to it and moves to the next drive in the rotation.

### Can I back up network shares?
Yes, provided the network share is mapped to a drive letter or accessible via UNC paths in Windows and the service account running the task has permissions to access it.

### Can I run it on multiple computers?
Yes, you can install it on multiple computers. However, they will operate independently unless they are configured to point to the exact same cloud directories (which is generally for advanced users only).

### Does it support incremental backups?
Yes. After the initial full backup, subsequent runs only upload new or modified files, minimizing backup time and bandwidth usage.

### Can I pause backups?
You can stop an active backup from the dashboard or disable the Windows Scheduled Task to pause automatic backups.

## Management & Troubleshooting

### How do I check if a backup ran successfully?
You can view the status of past and current backups, including logs, directly in the web dashboard on port 8080.

### How do I update the application?
Updates are typically performed by pulling the latest release from the repository and running the provided update script. Check the project documentation for version-specific instructions.

### Can I run this without the web dashboard?
Yes, the underlying backup engine operates independently via a Windows Scheduled Task. The dashboard is primarily for configuration and monitoring.
