# CloudBackup for Windows - Architecture

## 1. Overview
CloudBackup for Windows is a robust, lightweight backup solution designed specifically for Windows hosts. It is built to seamlessly transfer files from source PCs and servers to various cloud target remotes. Driven by a Python-based Backup Engine, it integrates file scanning, content-addressed deduplication, military-grade encryption, and dynamic storage rotation. All components are designed to ensure data integrity and maximize storage efficiency while remaining easily configurable.

## 2. Architecture Diagram

![Architecture](docs/screenshots/architecture.jpg)
*Figure 1: End-to-end data flow and component interaction within CloudBackup for Windows.*

## 3. Components

| Component | Purpose | Location |
|-----------|---------|----------|
| Backup Engine | Orchestrates the entire backup process and handles core logic. | Python Core |
| File Scanner | Identifies modified and new files on the local filesystem. | Backup Engine |
| Deduplication Engine | Splits files into chunks and prevents redundant uploads. | Backup Engine |
| Encryption | Encrypts data client-side before transmission using AES-256. | rclone crypt |
| Upload Manager | Manages remote connections and handles network transfers. | rclone |
| Rotation Controller | Monitors storage usage and switches cloud drives at thresholds. | Backup Engine |
| Catalog DB | Maintains a record of all backed-up files, chunks, and metadata. | SQLite Database |
| Web Dashboard | Provides a user-friendly interface to configure and monitor backups. | Python HTTP Server |

## 4. Data Flow

The backup process follows a streamlined path from the local host to the cloud target:

1. **Scan Initiation:** The Backup Engine initiates a scan of the local directories specified in the configuration.
2. **Metadata Extraction:** The File Scanner reads file metadata (size, modification time) to identify changes.
3. **Chunking and Hashing:** Modified files are passed to the Deduplication Engine. Files are split into chunks, and each chunk is uniquely hashed (content-addressed).
4. **Deduplication Check:** The engine queries the Catalog DB. If a chunk's hash already exists, it is skipped.
5. **Encryption:** Unique chunks are sent to the rclone crypt remote. Data is encrypted locally using AES-256.
6. **Upload:** The Upload Manager securely transmits the encrypted chunks to the current active cloud remote.
7. **Rotation Check:** After uploading, the Rotation Controller evaluates remote storage capacity. If the fill threshold is exceeded, the active remote is swapped to the next available target.
8. **Catalog Update:** The Catalog DB is updated with the new file metadata and chunk mappings.

## 5. Deduplication

CloudBackup utilizes a content-addressed deduplication approach. This means the system identifies data based on its content, not its file name or location. 

When a file is processed, it is broken down into smaller pieces called "chunks." Each chunk receives a unique cryptographic signature or "hash." Before uploading a chunk, the Backup Engine checks if that specific hash is already recorded in the SQLite catalog. If the hash exists, the system knows that exact piece of data is already stored in the cloud. It simply creates a new reference to the existing chunk. This drastically reduces backup time and saves cloud storage space.

## 6. Encryption

Security is a primary focus. CloudBackup integrates with rclone's crypt system to ensure that all data is encrypted before it ever leaves your machine. 

It uses AES-256 encryption, which is standard for securing sensitive information. The encryption process wraps the data locally. Crucially, your encryption keys are stored entirely on your local machine and are never transmitted to or stored in the cloud provider. Even if a cloud remote is compromised, the stored data remains unreadable.

## 7. Drive Rotation

To manage storage limits on consumer cloud accounts, CloudBackup features a Rotation Controller. You can specify a "fill threshold" (e.g., 90% capacity). 

When a backup runs, the Rotation Controller monitors the storage quota of the currently active remote. Once the usage surpasses the defined threshold, the controller automatically updates the system state to use the next remote in your configured list. This allows you to pool multiple smaller cloud drives (like multiple Google Drive accounts) into one massive logical backup target.

## 8. Configuration Files

System configuration is defined in a clear, human-readable YAML format. The `config.yaml` file dictates the source paths, remote definitions, and thresholds. State information, such as the currently active drive, is stored separately in `state.json`.

```yaml
# Example config.yaml (Generic Values)
backup_sources:
  - path: "C:\\Users\\Public\\Documents"
  - path: "D:\\ImportantData"

remotes:
  - name: "gdrive1"
    provider: "drive"
    threshold_percent: 90
  - name: "onedrive1"
    provider: "onedrive"
    threshold_percent: 85

encryption:
  enabled: true
  password: "YOUR_SECURE_PASSWORD" # Store securely
  salt: "YOUR_SECURE_SALT"

schedule:
  daily_at: "02:00"
```

## 9. Cloud Provider Integration

CloudBackup abstracts cloud storage through the `rclone` utility. Remotes are defined in pairs: a base remote and a crypt remote. 

For example, a Google Drive target might have a base remote named `gdrive1:`. The encryption layer is built on top of this as `gdrive1_crypt:`. The Backup Engine always interacts with the crypt remote, ensuring that data is automatically encrypted. Providers like Google Drive, Microsoft OneDrive, and Microsoft Teams SharePoint are supported as long as they can be configured via rclone.

## 10. Web Dashboard

For ease of use, CloudBackup includes a built-in Web Dashboard. 

It runs on a lightweight Python HTTP server (using `BaseHTTPRequestHandler`), typically on port 8080. The backend provides a REST API that interfaces with the Backup Engine. The frontend is built with standard HTML and JavaScript, offering a clean interface to monitor backup progress, configure settings, and manage remote connections without needing to edit configuration files manually.

## 11. Backup Catalog

The Backup Catalog is the brain of the deduplication system. It is implemented as a local SQLite database. 

This database maintains tables for:
*   **Files:** Tracking full paths, sizes, and timestamps.
*   **Chunks:** Storing the content hashes and their storage locations in the cloud.
*   **File-to-Chunk Mappings:** Linking files to the specific chunks that comprise them.

Using SQLite ensures the catalog is portable, fast, and does not require complex database server installations on the host Windows machine.

## 12. Scheduling

Regular backups are essential. CloudBackup integrates natively with the Windows Task Scheduler. 

Instead of running a continuous background service that consumes system resources, the Backup Engine registers a scheduled task during installation or via the dashboard. This task wakes up the Python process at the designated times (e.g., daily at 2 AM) to perform the backup, ensuring minimal impact on daytime system performance.
