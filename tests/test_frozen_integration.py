"""
tests/test_frozen_integration.py — Integration test for frozen resource resolution,
single-instance locking, loopback web server routing, and schema loading.
"""

import http.client
import threading
import time
import unittest
from pathlib import Path

from shared.paths import (
    SingleInstanceLock,
    get_resource_path,
    get_state_dir,
    is_frozen,
)
from windows.web_server import run_windows_server


class TestFrozenIntegration(unittest.TestCase):

    def test_resource_discovery_integrity(self):
        """Verify essential static assets and SQL schema exist via get_resource_path."""
        schema_path = get_resource_path("shared/schema.sql")
        self.assertTrue(schema_path.exists(), f"schema.sql missing at {schema_path}")
        schema_text = schema_path.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE", schema_text)

        index_path = get_resource_path("windows/web_static/index.html")
        self.assertTrue(index_path.exists(), f"index.html missing at {index_path}")
        index_text = index_path.read_text(encoding="utf-8")
        self.assertIn("<html", index_text.lower())

    def test_single_instance_locking(self):
        """Verify process-wide single instance locking mechanism."""
        lock_file = get_state_dir() / "test_integration.lock"
        lock1 = SingleInstanceLock(lock_file)
        self.assertTrue(lock1.acquire())

        lock2 = SingleInstanceLock(lock_file)
        self.assertFalse(lock2.acquire())

        lock1.release()
        self.assertTrue(lock2.acquire())
        lock2.release()

    def test_loopback_server_security_rejection(self):
        """Verify that non-loopback host parameters are strictly rejected."""
        with self.assertRaises(ValueError):
            run_windows_server(host="0.0.0.0", port=8766)

        with self.assertRaises(ValueError):
            run_windows_server(host="192.168.1.100", port=8766)


if __name__ == "__main__":
    unittest.main()
