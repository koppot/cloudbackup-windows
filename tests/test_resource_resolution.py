"""
tests/test_resource_resolution.py — Unit tests for frozen & source mode resource resolution.
"""

import unittest
from pathlib import Path
from shared.paths import get_app_dir, get_resource_path, is_frozen


class TestResourceResolution(unittest.TestCase):

    def test_app_dir_resolution(self):
        app_dir = get_app_dir()
        self.assertTrue(app_dir.exists())
        self.assertTrue(app_dir.is_dir())

    def test_bundled_resource_resolution(self):
        schema_path = get_resource_path("shared/schema.sql")
        self.assertTrue(schema_path.exists(), f"schema.sql not found at {schema_path}")
        self.assertTrue(schema_path.is_file())

        index_path = get_resource_path("windows/web_static/index.html")
        self.assertTrue(index_path.exists(), f"index.html not found at {index_path}")
        self.assertTrue(index_path.is_file())

    def test_frozen_flag(self):
        # Should be False in normal python test environment
        self.assertFalse(is_frozen())


if __name__ == "__main__":
    unittest.main()
