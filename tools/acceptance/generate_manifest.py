#!/usr/bin/env python3
"""
Generate Source Checksum Manifest for Phase 1 VM Acceptance Testing.

Recursively scans a target source directory, computes SHA-256 hashes for all files,
and produces JSON, CSV, and text manifests for cryptographic verification.
"""

import os
import sys
import hashlib
import json
import csv
import argparse
from pathlib import Path

def generate_manifest(root_dir: Path) -> dict:
    """Recursively scan root_dir and compute relative path, size, and SHA-256 hash for every file."""
    root_dir = root_dir.resolve()
    if not root_dir.exists() or not root_dir.is_dir():
        raise ValueError(f"Source directory does not exist or is not a directory: {root_dir}")

    files_manifest = []

    for path in sorted(root_dir.rglob("*")):
        if path.is_file():
            rel_path = path.relative_to(root_dir).as_posix()
            hasher = hashlib.sha256()
            size_bytes = 0
            with open(path, "rb") as f:
                while chunk := f.read(65536):
                    hasher.update(chunk)
                    size_bytes += len(chunk)
            
            files_manifest.append({
                "relative_path": rel_path,
                "size_bytes": size_bytes,
                "sha256": hasher.hexdigest()
            })

    return {
        "source_root": str(root_dir),
        "total_files": len(files_manifest),
        "total_bytes": sum(f["size_bytes"] for f in files_manifest),
        "files": files_manifest
    }

def save_manifests(manifest_data: dict, output_base: Path):
    """Save manifest in JSON, CSV, and TXT formats."""
    output_base.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. JSON
    json_path = output_base.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)
    print(f"[OK] Saved JSON manifest: {json_path}")

    # 2. CSV
    csv_path = output_base.with_suffix(".csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["relative_path", "size_bytes", "sha256"])
        for item in manifest_data["files"]:
            writer.writerow([item["relative_path"], item["size_bytes"], item["sha256"]])
    print(f"[OK] Saved CSV manifest: {csv_path}")

    # 3. TXT
    txt_path = output_base.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Source Root: {manifest_data['source_root']}\n")
        f.write(f"Total Files: {manifest_data['total_files']}\n")
        f.write(f"Total Bytes: {manifest_data['total_bytes']}\n\n")
        for item in manifest_data["files"]:
            f.write(f"{item['sha256']}  {item['relative_path']} ({item['size_bytes']} bytes)\n")
    print(f"[OK] Saved TXT manifest: {txt_path}")

def main():
    parser = argparse.ArgumentParser(description="Generate checksum manifest for target directory.")
    parser.add_argument("--source-dir", required=True, help="Directory to scan.")
    parser.add_argument("--output-base", required=True, help="Base output path (without extension) for manifests.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    output_base = Path(args.output_base)

    print(f"Scanning source directory: {source_dir}")
    manifest = generate_manifest(source_dir)
    save_manifests(manifest, output_base)

if __name__ == "__main__":
    main()
