"""
tests/test_subprocess_safety.py — Unit tests for shared/subprocess_utils.py.
"""

import sys
import unittest
from shared.subprocess_utils import (
    redact_cmd_list,
    redact_secrets,
    run_safe_subprocess,
)


class TestSubprocessSafety(unittest.TestCase):

    def test_redact_secrets_in_string(self):
        text = 'Account token {"access_token": "secret_oauth_token_xyz123"} Bearer secret_bearer_token'
        redacted = redact_secrets(text)
        self.assertNotIn("secret_oauth_token_xyz123", redacted)
        self.assertNotIn("secret_bearer_token", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_redact_cmd_list(self):
        cmd = ["rclone", "copy", "source", "dest", "--password", "SuperSecretPass123", "--token", "{\"access_token\":\"12345\"}"]
        redacted = redact_cmd_list(cmd)
        self.assertNotIn("SuperSecretPass123", redacted)
        self.assertNotIn("12345", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_run_safe_subprocess_invalid_cmd(self):
        with self.assertRaises(ValueError):
            run_safe_subprocess("")

        with self.assertRaises(TypeError):
            run_safe_subprocess(["ls", 123])

    def test_run_safe_subprocess_execution(self):
        # Run a simple safe command
        cmd = [sys.executable, "-c", "print('hello_world')"]
        res = run_safe_subprocess(cmd, timeout=5)
        self.assertTrue(res.success)
        self.assertIn("hello_world", res.stdout)
        self.assertEqual(res.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
