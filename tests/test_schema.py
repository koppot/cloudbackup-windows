"""
tests/test_schema.py — SQLite schema verification tests for ADC Backup System.

Verifies schema creation, default settings seeds, and append-only trigger enforcement on the 'runs' table.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent.parent / "shared" / "schema.sql"


class TestSchema(unittest.TestCase):

    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()

        if not SCHEMA_PATH.exists():
            self.fail(f"schema.sql file not found at: {SCHEMA_PATH}")

        with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
            schema_sql = fh.read()

        self.cursor.executescript(schema_sql)
        self.conn.commit()

    def tearDown(self) -> None:
        self.conn.close()

    def test_tables_exist(self) -> None:
        """Verify all expected tables exist in SQLite master catalog."""
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in self.cursor.fetchall()}

        expected_tables = {
            "remotes",
            "sources",
            "jobs",
            "runs",
            "restores",
            "settings",
            "system_state",
            "audit_log",
        }
        for table in expected_tables:
            self.assertIn(table, tables, f"Expected table '{table}' missing from schema")

    def test_default_settings_seed(self) -> None:
        """Verify default configuration seeds exist in settings table."""
        self.cursor.execute("SELECT key, value FROM settings;")
        settings = dict(self.cursor.fetchall())

        expected_keys = [
            "log_retention_days",
            "rclone_tpslimit",
            "rclone_transfers",
            "staging_dir",
        ]
        for key in expected_keys:
            self.assertIn(key, settings, f"Expected setting key '{key}' missing")

    def test_runs_table_append_only_update_trigger(self) -> None:
        """Verify that updating a row in the 'runs' table raises an exception."""
        self.cursor.execute(
            "INSERT INTO remotes (name, base_remote, crypt_remote) VALUES ('g1', 'g1:', 'g1_crypt:')"
        )
        remote_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO jobs (name, host, data_class) VALUES ('job1', 'supermicro.local', 'config')"
        )
        job_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO runs (job_id, remote_id, started_at, status) VALUES (?, ?, '2026-08-02T00:00:00Z', 'running')",
            (job_id, remote_id),
        )
        run_id = self.cursor.lastrowid
        self.conn.commit()

        with self.assertRaises((sqlite3.OperationalError, sqlite3.IntegrityError)) as ctx:
            self.cursor.execute(
                "UPDATE runs SET status = 'success' WHERE id = ?",
                (run_id,),
            )

        self.assertIn("runs table is append-only", str(ctx.exception))

    def test_runs_table_append_only_delete_trigger(self) -> None:
        """Verify that deleting a row from the 'runs' table raises an exception."""
        self.cursor.execute(
            "INSERT INTO remotes (name, base_remote, crypt_remote) VALUES ('g2', 'g2:', 'g2_crypt:')"
        )
        remote_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO jobs (name, host, data_class) VALUES ('job2', 'supermicro.local', 'data')"
        )
        job_id = self.cursor.lastrowid

        self.cursor.execute(
            "INSERT INTO runs (job_id, remote_id, started_at, status) VALUES (?, ?, '2026-08-02T00:00:00Z', 'failed')",
            (job_id, remote_id),
        )
        run_id = self.cursor.lastrowid
        self.conn.commit()

        with self.assertRaises((sqlite3.OperationalError, sqlite3.IntegrityError)) as ctx:
            self.cursor.execute(
                "DELETE FROM runs WHERE id = ?",
                (run_id,),
            )

        self.assertIn("runs table is append-only", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
