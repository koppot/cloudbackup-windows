"""
tests/test_rclone_discovery.py — Unit tests for fail-closed rclone discovery policy.
"""

import os
import unittest
from pathlib import Path
from shared.rclone import resolve_rclone_binary


class TestRcloneDiscovery(unittest.TestCase):

    def test_prohibit_relative_or_path_override(self):
        # Bare 'rclone' or relative override should be rejected
        with self.assertRaises(ValueError):
            resolve_rclone_binary("rclone")

        with self.assertRaises(ValueError):
            resolve_rclone_binary("custom/rclone.exe")

    def test_nonexistent_external_override(self):
        fake_abs_path = os.path.abspath("/nonexistent_path/rclone.exe")
        with self.assertRaises(FileNotFoundError):
            resolve_rclone_binary(fake_abs_path)


if __name__ == "__main__":
    unittest.main()
