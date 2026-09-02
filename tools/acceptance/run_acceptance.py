#!/usr/bin/env python3
"""
Cross-Platform Acceptance Test Suite Runner for Phase 1 VM Acceptance Tooling.

Runs synthetic data generation, checksum manifest creation, simulated restore verification,
and evidence collection to validate acceptance tools on Linux, macOS, and Windows hosts.
"""

import os
import sys
import shutil
import tempfile
import json
from pathlib import Path

# Add tools/acceptance to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from generate_synthetic_data import create_synthetic_dataset
from generate_manifest import generate_manifest, save_manifests
from verify_restore import verify_restore
from collect_evidence import collect_evidence

def main():
    print("================================================================================")
    print(" CloudBackup Phase 1 Acceptance Tooling Self-Verification")
    print("================================================================================")

    temp_dir = Path(tempfile.mkdtemp(prefix="cloudbackup_acceptance_test_"))
    try:
        source_dir = temp_dir / "source"
        restore_dir = temp_dir / "restore"
        artifacts_dir = temp_dir / "artifacts"

        print(f"\n[1] Testing Synthetic Dataset Creation in: {source_dir}")
        dataset = create_synthetic_dataset(source_dir)
        print(f"    [OK] Created {dataset['total_files']} files ({dataset['total_bytes']} bytes).")

        print(f"\n[2] Testing Checksum Manifest Generation...")
        manifest = generate_manifest(source_dir)
        manifest_base = artifacts_dir / "source_manifest"
        save_manifests(manifest, manifest_base)
        print("    [OK] Manifest JSON, CSV, and TXT written.")

        print(f"\n[3] Simulating Perfect Restore Tree...")
        shutil.copytree(source_dir, restore_dir)
        print("    [OK] Restored tree mirrored.")

        print(f"\n[4] Testing Restore Verification Engine...")
        report = verify_restore(manifest_base.with_suffix(".json"), restore_dir)
        if report["status"] != "PASS" or report["sha256_mismatch_count"] != 0:
            print(f"    [FAIL] Expected PASS with 0 mismatches, got: {report}")
            sys.exit(1)
        print("    [OK] Restore verification returned PASS with 0 SHA-256 mismatches.")

        print(f"\n[5] Testing Intentionally Corrupted Restore Detection...")
        # Corrupt one restored file
        corrupt_target = restore_dir / "documents" / "sample_text.txt"
        with open(corrupt_target, "ab") as f:
            f.write(b"CORRUPTION_BYTES_TEST")
        
        fail_report = verify_restore(manifest_base.with_suffix(".json"), restore_dir)
        if fail_report["status"] != "FAIL" or fail_report["sha256_mismatch_count"] == 0:
            print(f"    [FAIL] Expected FAIL on corrupted file, got: {fail_report}")
            sys.exit(1)
        print("    [OK] Restore verification engine correctly detected SHA-256 corruption.")

        print(f"\n[6] Testing Environment Evidence Collector...")
        evidence_path = artifacts_dir / "evidence.json"
        evidence = collect_evidence()
        with open(evidence_path, "w", encoding="utf-8") as f:
            json.dump(evidence, f, indent=2)
        print(f"    [OK] Evidence saved ({len(evidence)} top-level sections).")

        print("\n================================================================================")
        print(" [OK] All Phase 1 Acceptance Tools Verified Successfully!")
        print("================================================================================")
        return 0

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    sys.exit(main())
