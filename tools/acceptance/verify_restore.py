#!/usr/bin/env python3
"""
Verify Restored Dataset for Phase 1 VM Acceptance Testing.

Compares a restored directory against the original source directory or manifest.
Verifies file counts, relative paths, byte sizes, and cryptographic SHA-256 digests.
Fails with non-zero exit code if ANY mismatch exists.
"""

import os
import sys
import hashlib
import json
import argparse
from pathlib import Path

def compute_dir_manifest(root_dir: Path) -> dict:
    """Scan directory and return dict mapping relative_path -> {size_bytes, sha256}."""
    root_dir = root_dir.resolve()
    manifest = {}
    if not root_dir.exists():
        return manifest

    for path in root_dir.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(root_dir).as_posix()
            hasher = hashlib.sha256()
            size_bytes = 0
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
                    size_bytes += len(chunk)
            manifest[rel_path] = {
                "size_bytes": size_bytes,
                "sha256": hasher.hexdigest()
            }
    return manifest

def verify_restore(source_dir_or_manifest: Path, restored_dir: Path) -> dict:
    """Compare source against restored directory."""
    restored_dir = restored_dir.resolve()

    if source_dir_or_manifest.is_file() and source_dir_or_manifest.suffix == ".json":
        with open(source_dir_or_manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "files" in data and isinstance(data["files"], list):
                source_manifest = {
                    item["relative_path"]: {"size_bytes": item["size_bytes"], "sha256": item["sha256"]}
                    for item in data["files"]
                }
            else:
                source_manifest = data
    else:
        source_manifest = compute_dir_manifest(source_dir_or_manifest)

    restored_manifest = compute_dir_manifest(restored_dir)

    source_keys = set(source_manifest.keys())
    restored_keys = set(restored_manifest.keys())

    missing_files = sorted(list(source_keys - restored_keys))
    unexpected_files = sorted(list(restored_keys - source_keys))
    common_files = sorted(list(source_keys & restored_keys))

    size_mismatches = []
    sha256_mismatches = []
    matching_files = []

    for rel_path in common_files:
        src = source_manifest[rel_path]
        dst = restored_manifest[rel_path]

        has_error = False
        if src["size_bytes"] != dst["size_bytes"]:
            size_mismatches.append({
                "relative_path": rel_path,
                "source_bytes": src["size_bytes"],
                "restored_bytes": dst["size_bytes"]
            })
            has_error = True

        if src["sha256"] != dst["sha256"]:
            sha256_mismatches.append({
                "relative_path": rel_path,
                "source_sha256": src["sha256"],
                "restored_sha256": dst["sha256"]
            })
            has_error = True

        if not has_error:
            matching_files.append(rel_path)

    passed = (
        len(missing_files) == 0 and
        len(unexpected_files) == 0 and
        len(size_mismatches) == 0 and
        len(sha256_mismatches) == 0 and
        len(matching_files) == len(source_manifest)
    )

    report = {
        "status": "PASS" if passed else "FAIL",
        "source_file_count": len(source_manifest),
        "restored_file_count": len(restored_manifest),
        "matching_file_count": len(matching_files),
        "missing_file_count": len(missing_files),
        "unexpected_file_count": len(unexpected_files),
        "size_mismatch_count": len(size_mismatches),
        "sha256_mismatch_count": len(sha256_mismatches),
        "details": {
            "missing_files": missing_files,
            "unexpected_files": unexpected_files,
            "size_mismatches": size_mismatches,
            "sha256_mismatches": sha256_mismatches
        }
    }
    return report

def main():
    parser = argparse.ArgumentParser(description="Verify restored backup dataset against source manifest/directory.")
    parser.add_argument("--source", required=True, help="Path to original source directory or source manifest.json.")
    parser.add_argument("--restored-dir", required=True, help="Path to restored directory.")
    parser.add_argument("--report-out", help="Path to save verification JSON report.")
    args = parser.parse_args()

    source_path = Path(args.source)
    restored_path = Path(args.restored_dir)

    print(f"Comparing Source ({source_path}) vs Restored ({restored_path})...")
    report = verify_restore(source_path, restored_path)

    print("\n--- RESTORE VERIFICATION SUMMARY ---")
    print(f"Result: {report['status']}")
    print(f"Source File Count:    {report['source_file_count']}")
    print(f"Restored File Count:  {report['restored_file_count']}")
    print(f"Matching Files:       {report['matching_file_count']}")
    print(f"Missing Files:        {report['missing_file_count']}")
    print(f"Unexpected Files:     {report['unexpected_file_count']}")
    print(f"Size Mismatches:      {report['size_mismatch_count']}")
    print(f"SHA-256 Mismatches:   {report['sha256_mismatch_count']}")

    if args.report_out:
        report_file = Path(args.report_out)
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\nSaved report artifact: {report_file}")

    if report["status"] != "PASS":
        print("\n[FAIL] Restore verification failed due to mismatches.")
        sys.exit(1)
    else:
        print("\n[OK] Restore verification PASSED with 0 SHA-256 mismatches.")
        sys.exit(0)

if __name__ == "__main__":
    main()
