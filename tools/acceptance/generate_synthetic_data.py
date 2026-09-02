#!/usr/bin/env python3
"""
Generate Synthetic Backup Dataset for Phase 1 VM Acceptance Testing.

Creates a deterministic synthetic test folder structure containing:
- Plain text files
- Binary files (random bytes & repetitive patterns)
- Nested directories
- Paths and folders containing spaces
- Unicode filenames (accents, Asian, Cyrillic)
- Long valid paths
- Windows-permitted punctuation
- Duplicate content files (same content, different paths)
- Multi-megabyte file to exercise multichunk / copy behavior

All files are created inside a single isolated target directory.
"""

import os
import sys
import hashlib
import json
import argparse
from pathlib import Path

def create_synthetic_dataset(target_dir: Path) -> dict:
    """Create the synthetic test dataset under target_dir and return file manifest dict."""
    target_dir = target_dir.resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    files_created = []

    def write_file(rel_path: str, content: bytes):
        full_path = target_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)
        
        sha256 = hashlib.sha256(content).hexdigest()
        files_created.append({
            "relative_path": str(Path(rel_path).as_posix()),
            "size_bytes": len(content),
            "sha256": sha256
        })

    # 1. Plain text files
    write_file("documents/sample_text.txt", b"CloudBackup Phase 1 Acceptance Test File\nLine 2\nLine 3\n")
    write_file("documents/notes.md", b"# Acceptance Notes\n- Zero SHA-256 mismatches required\n- Non-admin runtime verified\n")

    # 2. Binary files
    binary_pattern = bytes([i % 256 for i in range(4096)])
    write_file("binaries/pattern.bin", binary_pattern)

    # 3. Large multichunk binary file (~5 MB)
    large_chunk = b"CLOUDBACKUP_TEST_CHUNK_BLOCK_5MB_" * 16384  # ~524KB * 10
    large_binary = large_chunk * 10
    write_file("binaries/large_multichunk_5mb.dat", large_binary)

    # 4. Folder and files with spaces
    write_file("Folder With Spaces/Sub Folder/file with spaces in name.txt", b"Content inside folder with spaces.\n")

    # 5. Unicode filenames
    write_file("unicode/Ünicodë_测试_Файл.txt", "Unicode content: UTF-8 encoding verified.\n".encode("utf-8"))
    write_file("unicode/español_français_deutsch.txt", "Café, René, Straße, Señor.\n".encode("utf-8"))

    # 6. Windows-permitted punctuation
    write_file("punctuation/file-1.2_test(1)[2]{3}#4$5%6&7.txt", b"Punctuation test file content.\n")

    # 7. Long nested Windows path
    long_rel = "nested/a/very/deeply/nested/directory/structure/that/tests/long/windows/file/path/handling/long_path_file.txt"
    write_file(long_rel, b"Deep path file content verification.\n")

    # 8. Duplicate content files
    duplicate_content = b"DUPLICATE_FILE_CONTENT_IDENTICAL_HASH_CHECK_1234567890\n"
    write_file("duplicates/original.txt", duplicate_content)
    write_file("duplicates/copy_of_original.txt", duplicate_content)
    write_file("duplicates/nested_folder/another_copy.txt", duplicate_content)

    return {
        "target_dir": str(target_dir),
        "total_files": len(files_created),
        "total_bytes": sum(f["size_bytes"] for f in files_created),
        "files": sorted(files_created, key=lambda x: x["relative_path"])
    }

def main():
    parser = argparse.ArgumentParser(description="Generate synthetic backup test dataset.")
    parser.add_argument("--output-dir", required=True, help="Target directory for synthetic files.")
    parser.add_argument("--manifest-out", help="Path to save JSON manifest.")
    args = parser.parse_args()

    output_path = Path(args.output_dir)
    print(f"Creating synthetic test dataset in: {output_path}")

    dataset = create_synthetic_dataset(output_path)

    print(f"[OK] Generated {dataset['total_files']} synthetic files ({dataset['total_bytes']} bytes).")

    if args.manifest_out:
        manifest_path = Path(args.manifest_out)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(dataset, f, indent=2, ensure_ascii=False)
        print(f"[OK] Manifest saved to: {manifest_path}")

if __name__ == "__main__":
    main()
