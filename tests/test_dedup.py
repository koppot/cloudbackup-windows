"""
tests/test_dedup.py — Unit tests for pre-upload file-level deduplication engine.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from shared.dedup import compute_file_fingerprint, scan_and_deduplicate, save_catalog_batch

SCHEMA_PATH = Path(__file__).parent.parent / "shared" / "schema.sql"


class TestFileDeduplication(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")

        conn = sqlite3.connect(self.db_path)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())

        conn.execute("INSERT INTO remotes (id, name, base_remote, crypt_remote) VALUES (1, 'g1', 'g1:', 'g1_crypt:')")
        conn.commit()
        conn.close()

        # Create dummy test files
        self.file1 = Path(self.temp_dir.name) / "test1.txt"
        self.file2 = Path(self.temp_dir.name) / "test2.txt"

        self.file1.write_text("Hello ADC Backup Deduplication!", encoding="utf-8")
        self.file2.write_text("Unique File Content 12345", encoding="utf-8")

    def tearDown(self) -> None:
        os.close(self.db_fd)
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        self.temp_dir.cleanup()

    def test_fingerprint_computation(self) -> None:
        sha256, size, mtime = compute_file_fingerprint(str(self.file1))
        self.assertIsInstance(sha256, str)
        self.assertGreater(len(sha256), 30)
        self.assertEqual(size, len("Hello ADC Backup Deduplication!"))

    def test_first_scan_all_files_queued_for_upload(self) -> None:
        result = scan_and_deduplicate(
            source_paths=[str(self.file1), str(self.file2)],
            host="supermicro.local",

            data_class="config",
            remote_id=1,
            db_path=self.db_path,
        )

        self.assertEqual(len(result["to_upload"]), 2)
        self.assertEqual(len(result["deduplicated"]), 0)
        self.assertGreater(result["bytes_to_upload"], 0)

    def test_second_scan_unchanged_files_deduplicated(self) -> None:
        # First scan & save catalog
        res1 = scan_and_deduplicate(
            source_paths=[str(self.file1), str(self.file2)],
            host="supermicro.local",

            data_class="config",
            remote_id=1,
            db_path=self.db_path,
        )
        save_catalog_batch(res1["scanned_records"], run_id=1, db_path=self.db_path)

        # Second scan without modifying files
        res2 = scan_and_deduplicate(
            source_paths=[str(self.file1), str(self.file2)],
            host="supermicro.local",

            data_class="config",
            remote_id=1,
            db_path=self.db_path,
        )

        self.assertEqual(len(res2["to_upload"]), 0)
        self.assertEqual(len(res2["deduplicated"]), 2)
        self.assertGreater(res2["bytes_deduplicated"], 0)

    def test_modified_file_requeued_for_upload(self) -> None:
        # First scan & save catalog
        res1 = scan_and_deduplicate(
            source_paths=[str(self.file1)],
            host="supermicro.local",

            data_class="config",
            remote_id=1,
            db_path=self.db_path,
        )
        save_catalog_batch(res1["scanned_records"], run_id=1, db_path=self.db_path)

        # Modify file1
        self.file1.write_text("MODIFIED content for testing deduplication!", encoding="utf-8")

        res2 = scan_and_deduplicate(
            source_paths=[str(self.file1)],
            host="supermicro.local",

            data_class="config",
            remote_id=1,
            db_path=self.db_path,
        )

        self.assertEqual(len(res2["to_upload"]), 1)
        self.assertEqual(len(res2["deduplicated"]), 0)


if __name__ == "__main__":
    unittest.main()
