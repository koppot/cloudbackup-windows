"""
shared/dedup.py — File-Level Deduplication Engine for ADC Backup System.

Scans local source paths, computes streaming SHA-256 content fingerprints + mtime + file size,
and compares them against the SQLite `catalog_files` ledger for the target remote.

Unchanged files are skipped from transfer, while new/modified files are output to an rclone
`--files-from` manifest. All encryption, drive rotation, and ground-zero restore mechanics remain intact.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

log = logging.getLogger(__name__)


def compute_file_fingerprint(file_path: str, max_hash_bytes: int = 100 * 1024 * 1024) -> Tuple[str, int, str]:
    """
    Computes (sha256_hash, file_size, mtime_iso) for a local file.
    For files larger than max_hash_bytes, samples header, middle, and tail to maintain performance.
    """
    p = Path(file_path)
    stat = p.stat()
    file_size = stat.st_size
    mtime_iso = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()

    hasher = hashlib.sha256()

    if file_size <= max_hash_bytes:
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
    else:
        # Sampled hash for very large files (>100MB)
        hasher.update(f"{file_size}:{stat.st_mtime}".encode("utf-8"))
        with open(p, "rb") as f:
            hasher.update(f.read(65536))
            f.seek(file_size // 2)
            hasher.update(f.read(65536))
            f.seek(max(0, file_size - 65536))
            hasher.update(f.read(65536))

    return hasher.hexdigest(), file_size, mtime_iso


def scan_and_deduplicate(
    source_paths: List[str],
    host: str,
    data_class: str,
    remote_id: int,
    db_path: str,
) -> dict:
    """
    Scans source paths, checks file fingerprints against the catalog for remote_id.

    Returns dict with:
      - 'to_upload': list of absolute file paths to upload
      - 'deduplicated': list of absolute file paths skipped (fingerprint matched)
      - 'bytes_to_upload': total byte size of new/modified files
      - 'bytes_deduplicated': total byte size of skipped unchanged files
      - 'scanned_records': dict list for batch upserting into catalog_files
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Load existing catalog entries for this host and remote_id
    cursor.execute(
        "SELECT abs_path, sha256_hash, file_size, mtime_iso FROM catalog_files WHERE host = ? AND remote_id = ?",
        (host, remote_id),
    )
    existing_catalog = {row["abs_path"]: dict(row) for row in cursor.fetchall()}
    conn.close()

    to_upload: List[str] = []
    deduplicated: List[str] = []
    bytes_to_upload = 0
    bytes_deduplicated = 0
    scanned_records: List[dict] = []

    for src in source_paths:
        p = Path(src)
        if not p.exists():
            continue

        files_to_check = [p] if p.is_file() else list(p.rglob("*"))

        for f_path in files_to_check:
            if not f_path.is_file() or f_path.is_symlink():
                continue

            abs_str = str(f_path.resolve())
            try:
                sha256, size, mtime = compute_file_fingerprint(abs_str)
            except Exception as exc:
                log.warning("Could not compute fingerprint for %s: %s", abs_str, exc)
                to_upload.append(abs_str)
                continue

            cat_entry = existing_catalog.get(abs_str)

            if cat_entry and cat_entry["sha256_hash"] == sha256 and cat_entry["file_size"] == size:
                deduplicated.append(abs_str)
                bytes_deduplicated += size
            else:
                to_upload.append(abs_str)
                bytes_to_upload += size

            scanned_records.append({
                "host": host,
                "data_class": data_class,
                "abs_path": abs_str,
                "file_size": size,
                "mtime_iso": mtime,
                "sha256_hash": sha256,
                "remote_id": remote_id,
            })

    log.info(
        "Deduplication scan for host '%s' remote #%d: %d files (%s) queued for upload, %d files (%s) deduplicated.",
        host,
        remote_id,
        len(to_upload),
        f"{bytes_to_upload / (1024**2):.1f} MB",
        len(deduplicated),
        f"{bytes_deduplicated / (1024**2):.1f} MB",
    )

    return {
        "to_upload": to_upload,
        "deduplicated": deduplicated,
        "bytes_to_upload": bytes_to_upload,
        "bytes_deduplicated": bytes_deduplicated,
        "scanned_records": scanned_records,
    }


def save_catalog_batch(scanned_records: List[dict], run_id: int, db_path: str) -> None:
    """Batch upserts catalog records after a successful or partial backup run."""
    if not scanned_records:
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    now_iso = datetime.now(timezone.utc).isoformat()

    for rec in scanned_records:
        cursor.execute(
            """
            INSERT INTO catalog_files (
                host, data_class, abs_path, file_size, mtime_iso, sha256_hash,
                remote_id, first_seen_run_id, last_seen_run_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(host, remote_id, abs_path) DO UPDATE SET
                file_size = excluded.file_size,
                mtime_iso = excluded.mtime_iso,
                sha256_hash = excluded.sha256_hash,
                last_seen_run_id = excluded.last_seen_run_id,
                updated_at = excluded.updated_at
            """,
            (
                rec["host"],
                rec["data_class"],
                rec["abs_path"],
                rec["file_size"],
                rec["mtime_iso"],
                rec["sha256_hash"],
                rec["remote_id"],
                run_id,
                run_id,
                now_iso,
            ),
        )

    conn.commit()
    conn.close()
