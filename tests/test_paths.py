"""
tests/test_paths.py — Unit tests for shared/paths.py directory management & safety validation.
"""

import os
import unittest
from pathlib import Path

from shared.paths import (
    SingleInstanceLock,
    ensure_app_directories,
    get_app_dir,
    get_config_dir,
    get_log_dir,
    get_programdata_dir,
    get_resource_path,
    get_state_dir,
    get_temp_dir,
    validate_local_path,
)


class TestPaths(unittest.TestCase):

    def test_directory_resolution(self):
        pd = get_programdata_dir()
        self.assertIn("CloudBackup", str(pd))

        cfg_dir = get_config_dir()
        self.assertEqual(cfg_dir, pd / "config")

        state_dir = get_state_dir()
        self.assertEqual(state_dir, pd / "state")

        log_dir = get_log_dir()
        self.assertEqual(log_dir, pd / "logs")

        temp_dir = get_temp_dir()
        self.assertEqual(temp_dir, pd / "temp")

    def test_resource_resolution(self):
        res = get_resource_path("shared/schema.sql")
        self.assertTrue(res.exists(), f"Resource should exist at {res}")

    def test_validate_local_path_valid(self):
        cur = Path(__file__).resolve()
        validated = validate_local_path(str(cur), must_exist=True)
        self.assertEqual(validated, cur)

    def test_validate_local_path_normalization(self):
        # Test that '..' in a valid path normalizes safely
        parent_dir = Path(__file__).parent.resolve()
        input_path = str(parent_dir / ".." / "tests" / "test_paths.py")
        validated = validate_local_path(input_path, must_exist=True)
        self.assertEqual(validated, Path(__file__).resolve())

    def test_validate_local_path_nul_byte(self):
        with self.assertRaises(ValueError):
            validate_local_path("C:\\Path\\With\x00Nul", must_exist=False)

    def test_validate_local_path_reserved_name(self):
        with self.assertRaises(ValueError):
            validate_local_path("C:\\ProgramData\\CON.txt", must_exist=False)

        with self.assertRaises(ValueError):
            validate_local_path("C:\\ProgramData\\NUL", must_exist=False)

        with self.assertRaises(ValueError):
            validate_local_path("C:\\ProgramData\\AUX\\file.txt", must_exist=False)

    def test_validate_local_path_unc(self):
        # Valid UNC format
        unc_valid = "\\\\server\\share\\folder"
        val = validate_local_path(unc_valid, must_exist=False, allow_unc=True)
        self.assertIn("server", str(val))

        # Malformed UNC format
        with self.assertRaises(ValueError):
            validate_local_path("\\\\server", must_exist=False, allow_unc=True)

        # Prohibited UNC
        with self.assertRaises(ValueError):
            validate_local_path(unc_valid, must_exist=False, allow_unc=False)

    def test_single_instance_lock(self):
        lock1 = SingleInstanceLock()
        acquired1 = lock1.acquire()
        self.assertTrue(acquired1)

        lock2 = SingleInstanceLock()
        acquired2 = lock2.acquire()
        self.assertFalse(acquired2, "Second lock acquisition should fail")

        lock1.release()

        acquired3 = lock2.acquire()
        self.assertTrue(acquired3, "Lock acquisition should succeed after release")
        lock2.release()


if __name__ == "__main__":
    unittest.main()
