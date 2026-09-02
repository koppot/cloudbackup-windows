#!/usr/bin/env python3
"""
scripts/run_docker_tests.py — Hermetic Platform-Neutral Docker Test Runner

Executes platform-neutral regression test suite and repository secret scanner.
Outputs a structured test report clearly labeled as:
  "SUPPLEMENTARY PLATFORM-NEUTRAL VALIDATION ONLY"
"""

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

from scripts.scan_secrets import scan_repository

EXCLUDED_WINDOWS_TESTS = [
    "Inno Setup compilation (CloudBackup-Setup.exe)",
    "PyInstaller Windows x64 executable smoke test (CloudBackup.exe)",
    "Program Files / ProgramData ACL least-privilege enforcement",
    "UAC privilege elevation behavior",
    "Start Menu & Desktop shortcut creation",
    "Windows Task Scheduler & schtasks.exe registration",
    "Windows loopback listener & socket binding",
    "NTFS-specific path semantics & device name checks (CON, PRN, NUL)",
    "Windows rclone.exe execution",
    "Installer upgrade & data-purging uninstaller behavior",
]

PLATFORM_NEUTRAL_TEST_MODULES = [
    "tests.test_dedup",
    "tests.test_rotation",
    "tests.test_schema",
    "tests.test_subprocess_safety",
    "tests.test_resource_resolution",
]


def run_platform_neutral_tests() -> dict:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    for mod in PLATFORM_NEUTRAL_TEST_MODULES:
        try:
            suite.addTests(loader.loadTestsFromName(mod))
        except Exception as exc:
            print(f"[ERROR] Failed to load module {mod}: {exc}")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return {
        "total_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "was_successful": result.wasSuccessful(),
    }


def main() -> int:
    print("=" * 80)
    print("   CLOUD BACKUP FOR WINDOWS — SUPPLEMENTARY PLATFORM-NEUTRAL DOCKER VALIDATION")
    print("   LABEL: SUPPLEMENTARY PLATFORM-NEUTRAL VALIDATION ONLY")
    print("   (NOTE: Does NOT validate Windows installer or Windows security model)")
    print("=" * 80)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Python Version: {sys.version.split()[0]}")
    print(f"Working Directory: {ROOT_DIR}")

    # Check network isolation in container
    network_disabled = True
    try:
        import socket
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        network_disabled = False
        print("[WARN] Network connectivity detected! Container should run with --network none.")
    except Exception:
        print("✅ Network isolation confirmed: Container operating with --network none.")

    # 1. Run Repository Secret Scanner
    print("\n--- STAGE 1: REPOSITORY SECRET SCANNER ---")
    secret_exit = scan_repository()
    if secret_exit != 0:
        print("❌ Secret scanner failed. Halting test suite.")
        return 1

    # 2. Run Platform-Neutral Unit Test Suite
    print("\n--- STAGE 2: PLATFORM-NEUTRAL REGRESSION TESTS ---")
    test_res = run_platform_neutral_tests()

    # 3. Print Structured Execution Summary
    print("\n" + "=" * 80)
    print("                  DOCKER TEST SUITE SUMMARY REPORT")
    print("=" * 80)
    print(f"LABEL:                    SUPPLEMENTARY PLATFORM-NEUTRAL VALIDATION ONLY")
    print(f"Network Isolation:        {'CONFIRMED (--network none)' if network_disabled else 'UNCONSTRAINED'}")
    print(f"Platform-Neutral Tests:   {test_res['total_run']} executed ({test_res['total_run'] - test_res['failures'] - test_res['errors']} passed, {test_res['failures']} failed, {test_res['errors']} errors, {test_res['skipped']} skipped)")
    print(f"Secret Scanner:           PASSED")
    print("\nEXCLUDED WINDOWS-ONLY TEST SCOPE (Must be verified on clean Windows 11 VM):")
    for idx, item in enumerate(EXCLUDED_WINDOWS_TESTS, 1):
        print(f"  {idx:2d}. [EXCLUDED FROM DOCKER] {item}")

    print("=" * 80)

    if not test_res["was_successful"]:
        print("❌ Platform-neutral test suite FAILED.")
        return 1

    print("✅ Supplementary platform-neutral validation PASSED successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
