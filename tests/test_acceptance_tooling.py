"""
Unit and integration tests for Phase 1 VM Acceptance Tooling.
Verifies synthetic dataset creation, checksum manifest generation, restore verification,
corruption detection, and non-sensitive evidence collection.
"""

import os
import sys
import shutil
import tempfile
import json
from pathlib import Path
import pytest

# Add tools/acceptance to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "tools" / "acceptance"
sys.path.insert(0, str(SCRIPT_DIR))

from generate_synthetic_data import create_synthetic_dataset
from generate_manifest import generate_manifest, save_manifests
from verify_restore import verify_restore
from collect_evidence import collect_evidence

@pytest.fixture
def temp_acceptance_workspace():
    temp_dir = Path(tempfile.mkdtemp(prefix="cb_test_workspace_"))
    source_dir = temp_dir / "source"
    restore_dir = temp_dir / "restore"
    artifacts_dir = temp_dir / "artifacts"
    yield source_dir, restore_dir, artifacts_dir
    shutil.rmtree(temp_dir, ignore_errors=True)

def test_synthetic_data_and_manifest_generation(temp_acceptance_workspace):
    source_dir, _, artifacts_dir = temp_acceptance_workspace
    
    dataset = create_synthetic_dataset(source_dir)
    assert dataset["total_files"] == 12
    assert dataset["total_bytes"] > 5000000  # Multi-MB file included

    manifest = generate_manifest(source_dir)
    assert manifest["total_files"] == 12
    
    manifest_base = artifacts_dir / "source_manifest"
    save_manifests(manifest, manifest_base)

    assert manifest_base.with_suffix(".json").exists()
    assert manifest_base.with_suffix(".csv").exists()
    assert manifest_base.with_suffix(".txt").exists()

def test_verify_restore_perfect_match(temp_acceptance_workspace):
    source_dir, restore_dir, artifacts_dir = temp_acceptance_workspace
    
    create_synthetic_dataset(source_dir)
    manifest = generate_manifest(source_dir)
    manifest_base = artifacts_dir / "source_manifest"
    save_manifests(manifest, manifest_base)

    shutil.copytree(source_dir, restore_dir)

    report = verify_restore(manifest_base.with_suffix(".json"), restore_dir)
    assert report["status"] == "PASS"
    assert report["sha256_mismatch_count"] == 0
    assert report["size_mismatch_count"] == 0
    assert report["missing_file_count"] == 0
    assert report["unexpected_file_count"] == 0
    assert report["matching_file_count"] == 12

def test_verify_restore_detects_corruption_and_missing(temp_acceptance_workspace):
    source_dir, restore_dir, artifacts_dir = temp_acceptance_workspace
    
    create_synthetic_dataset(source_dir)
    manifest = generate_manifest(source_dir)
    manifest_base = artifacts_dir / "source_manifest"
    save_manifests(manifest, manifest_base)

    shutil.copytree(source_dir, restore_dir)

    # 1. Corrupt a file
    corrupt_file = restore_dir / "documents" / "sample_text.txt"
    with open(corrupt_file, "ab") as f:
        f.write(b"EXTRA_BAD_BYTES")

    # 2. Delete a file
    missing_file = restore_dir / "documents" / "notes.md"
    missing_file.unlink()

    report = verify_restore(manifest_base.with_suffix(".json"), restore_dir)
    assert report["status"] == "FAIL"
    assert report["missing_file_count"] == 1
    assert report["sha256_mismatch_count"] == 1

def test_collect_evidence_structure():
    evidence = collect_evidence()
    assert "platform" in evidence
    assert "user_identity" in evidence
    assert "path_binary_checks" in evidence
    assert "installation_directories" in evidence
