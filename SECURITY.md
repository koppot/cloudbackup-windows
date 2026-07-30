# Security Overview

Security and privacy are core priorities for CloudBackup for Windows. This document outlines how we protect your data.

## 1. Encryption Model
CloudBackup utilizes client-side, zero-knowledge encryption. 
- All files are encrypted locally on your machine before they are transmitted over the network.
- We use AES-256 encryption via the established `rclone crypt` backend.
- File names and directory structures are also encrypted to prevent information leakage.

## 2. Encryption Key Storage
Your encryption keys and salts are generated locally and stored exclusively in your local configuration files (e.g., `config.json` or dedicated key files).
- **We never upload your encryption keys to the cloud.**
- **We have no access to your keys.** 
- If you lose your keys, your data cannot be recovered. We strongly recommend securely backing up your configuration files to a password manager or a secure offline location.

## 3. What the Cloud Provider Can See
Because encryption happens before upload, your cloud storage providers (Google, Microsoft, etc.) can only see:
- Encrypted binary blobs.
- Encrypted file names.
- The total amount of data being stored.
They cannot see the contents of your files, your original file names, or your directory structures.

## 4. OAuth Token Storage
To interact with cloud APIs, CloudBackup uses OAuth tokens. These tokens are stored locally on your machine in the `rclone.conf` file. They are used solely to authenticate your local application with your cloud providers.

## 5. Dashboard Access
By default, the web dashboard binds only to `localhost` (`127.0.0.1`). 
- **Limitation:** The dashboard does not currently feature built-in user authentication (no username/password required).
- Because it only listens locally, it cannot be accessed from other devices on your network or the internet.
- If you manually reconfigure the application to listen on `0.0.0.0` to access it remotely, you do so at your own risk. We strongly advise against this unless you place it behind a secure reverse proxy with authentication.

## 6. Reporting Security Vulnerabilities
If you discover a security vulnerability in CloudBackup for Windows, please practice responsible disclosure. 
- Do not open a public GitHub issue for security flaws.
- Instead, please contact the maintainers directly at the security email listed in the repository, or use GitHub's private vulnerability reporting feature.
- We will acknowledge your report and work to release a patch as quickly as possible.

## 7. Dependency Security
We rely on standard, well-tested open-source libraries and tools, notably Python and `rclone`. We regularly update our dependencies to pull in upstream security patches. However, users should also ensure they are running supported versions of Python and keeping their Windows operating system up to date.

## 8. Recommendations for Production Use
- **Backup your config:** The most critical security step is ensuring you do not lose your local encryption keys.
- **Run as a standard user:** Where possible, run the scheduled task with the minimum permissions required to access your files.
- **Secure your PC:** Client-side encryption is only as secure as the client. Ensure your Windows machine is protected with strong passwords, disk encryption (like BitLocker), and appropriate anti-malware software.
