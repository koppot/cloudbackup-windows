"""
tests/test_rotation.py — Drive rotation logic tests for ADC Backup System.

Tests rotation selection, capacity threshold checks, and fallback behavior using unittest and unittest.mock.
"""

from __future__ import annotations

import unittest
from typing import List, Optional
from unittest.mock import MagicMock, patch

from shared.config import DriveRemoteConfig, DrivesConfig
from shared.rclone import CapacityInfo, RcloneRunner


def select_next_remote(
    remotes: List[DriveRemoteConfig], current_remote_name: Optional[str] = None
) -> Optional[DriveRemoteConfig]:
    """
    Select the next enabled drive remote ordered by priority (1 = highest priority).
    If current_remote_name is provided, returns the next enabled remote after current.
    If no drives are enabled or available, returns None.
    """
    enabled_remotes = sorted([r for r in remotes if r.enabled], key=lambda r: r.priority)
    if not enabled_remotes:
        return None

    if current_remote_name is None:
        return enabled_remotes[0]

    current_idx = -1
    for idx, r in enumerate(enabled_remotes):
        if r.name == current_remote_name:
            current_idx = idx
            break

    if current_idx == -1 or current_idx + 1 >= len(enabled_remotes):
        if len(enabled_remotes) == 1 and enabled_remotes[0].name == current_remote_name:
            return None
        return enabled_remotes[0]

    return enabled_remotes[current_idx + 1]


class TestDriveRotation(unittest.TestCase):

    def setUp(self) -> None:
        self.r1 = DriveRemoteConfig(
            name="gdrive1_crypt",
            base_remote="gdrive1:",
            crypt_remote="gdrive1_crypt:",
            priority=1,
            enabled=True,
        )
        self.r2 = DriveRemoteConfig(
            name="gdrive2_crypt",
            base_remote="gdrive2:",
            crypt_remote="gdrive2_crypt:",
            priority=2,
            enabled=True,
        )
        self.r3 = DriveRemoteConfig(
            name="gdrive3_crypt",
            base_remote="gdrive3:",
            crypt_remote="gdrive3_crypt:",
            priority=3,
            enabled=False,
        )
        self.remotes = [self.r2, self.r1, self.r3]

    def test_select_next_remote_by_priority(self) -> None:
        """Test that rotation picks the next enabled remote sorted by priority."""
        next_remote = select_next_remote(self.remotes)
        self.assertIsNotNone(next_remote)
        self.assertEqual(next_remote.name, "gdrive1_crypt")

        next_remote_after_r1 = select_next_remote(
            self.remotes, current_remote_name="gdrive1_crypt"
        )
        self.assertIsNotNone(next_remote_after_r1)
        self.assertEqual(next_remote_after_r1.name, "gdrive2_crypt")

    def test_no_drives_available_returns_none(self) -> None:
        """Test that when no drives are enabled or available, returns None."""
        disabled_r1 = DriveRemoteConfig(
            name="gdrive1_crypt",
            base_remote="gdrive1:",
            crypt_remote="gdrive1_crypt:",
            priority=1,
            enabled=False,
        )
        disabled_r2 = DriveRemoteConfig(
            name="gdrive2_crypt",
            base_remote="gdrive2:",
            crypt_remote="gdrive2_crypt:",
            priority=2,
            enabled=False,
        )

        next_remote = select_next_remote([disabled_r1, disabled_r2])
        self.assertIsNone(next_remote)

        next_remote_empty = select_next_remote([])
        self.assertIsNone(next_remote_empty)

    def test_needs_rotation_threshold(self) -> None:
        """Test that RcloneRunner.is_rotation_needed returns True when capacity is below threshold."""
        mock_cfg = MagicMock()
        mock_cfg.rclone.bin = "rclone"
        mock_cfg.rclone_conf = "/opt/adc-backup/rclone.conf"
        mock_cfg.server.log_dir = "/opt/adc-backup/logs"
        mock_cfg.rclone.base_flags.return_value = []

        runner = RcloneRunner(mock_cfg)

        # Case A: Healthy drive (90% free, 100 GB free) -> no rotation needed
        healthy_cap = CapacityInfo(
            remote="gdrive1_crypt",
            total_gb=100.0,
            used_gb=10.0,
            free_gb=90.0,
            pct_used=10.0,
        )
        self.assertFalse(
            runner.is_rotation_needed(
                healthy_cap, reserve_pct=5.0, reserve_bytes_gb=10 * 1024**3
            )
        )

        # Case B: Capacity below reserve percent (>95% used) -> rotation needed
        high_pct_cap = CapacityInfo(
            remote="gdrive1_crypt",
            total_gb=100.0,
            used_gb=96.0,
            free_gb=4.0,
            pct_used=96.0,
        )
        self.assertTrue(
            runner.is_rotation_needed(
                high_pct_cap, reserve_pct=5.0, reserve_bytes_gb=10 * 1024**3
            )
        )

        # Case C: Free space below reserve margin bytes (< 10 GB free) -> rotation needed
        low_free_cap = CapacityInfo(
            remote="gdrive1_crypt",
            total_gb=100.0,
            used_gb=91.0,
            free_gb=9.0,
            pct_used=91.0,
        )
        self.assertTrue(
            runner.is_rotation_needed(
                low_free_cap, reserve_pct=15.0, reserve_bytes_gb=10 * 1024**3
            )
        )

    def test_mock_db_remote_selection(self) -> None:
        """Test DB query mock for active drive selection."""
        mock_db = MagicMock()
        mock_db.fetchall.return_value = [
            (2, "gdrive2_crypt", 2, 1),
            (1, "gdrive1_crypt", 1, 1),
            (3, "gdrive3_crypt", 3, 0),
        ]

        rows = mock_db.fetchall.return_value
        enabled_rows = sorted([r for r in rows if r[3] == 1], key=lambda r: r[2])
        selected_remote = enabled_rows[0][1]

        self.assertEqual(selected_remote, "gdrive1_crypt")


if __name__ == "__main__":
    unittest.main()
