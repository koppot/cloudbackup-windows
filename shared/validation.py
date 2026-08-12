"""
shared/validation.py — Non-Destructive Evidence Validation & DR Readiness Subsystem for CloudBackup for Windows.

Strict Safety Contract:
- Read-only toward backup data, source files, state.db, databases, services, and cloud remotes.
- Controlled local report files created strictly in a scratch output root verified outside backup scope.
- Zero secret, token, credential, raw exception, or un-sanitized content logging/serialization.
- Fail-closed evaluation rules: missing or inaccessible evidence yields NOT_VERIFIED or BLOCKED.
- Lower-level file descriptor safety: os.O_RDONLY, os.O_NOFOLLOW (fail-closed if missing), os.O_CLOEXEC,
  fstat regular file check, pre/post read identity verification (ARTIFACT_CHANGED_DURING_VALIDATION),
  and pre-read size caps.
- Phase 0.1 Contract: In-place raw SHA-256 computation, two-pass gzip identity stability,
  digest-bound engine attestation (engine_attestation_v1), host-path mapping verification (host_path_map_v1),
  transient crypt remote names, and sanitized evidence_manifest.json generation.
"""

from __future__ import annotations

import enum
import gzip
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

# ─── Allowed Fixed Error Codes ────────────────────────────────────────────────
PATH_OUTSIDE_ALLOWED_ROOT = "PATH_OUTSIDE_ALLOWED_ROOT"
PATH_SYMLINK_REJECTED = "PATH_SYMLINK_REJECTED"
PATH_NOT_FOUND = "PATH_NOT_FOUND"
PATH_NOT_REGULAR_FILE = "PATH_NOT_REGULAR_FILE"
ARTIFACT_CHANGED_DURING_VALIDATION = "ARTIFACT_CHANGED_DURING_VALIDATION"
ARTIFACT_IDENTITY_MISMATCH = "ARTIFACT_IDENTITY_MISMATCH"
MANIFEST_TOO_LARGE = "MANIFEST_TOO_LARGE"
MANIFEST_DECODE_ERROR = "MANIFEST_DECODE_ERROR"
MANIFEST_LINE_TOO_LONG = "MANIFEST_LINE_TOO_LONG"
MANIFEST_ENTRY_LIMIT_EXCEEDED = "MANIFEST_ENTRY_LIMIT_EXCEEDED"
MANIFEST_INVALID_ENTRY = "MANIFEST_INVALID_ENTRY"
MANIFEST_EXCLUDED_PATH = "MANIFEST_EXCLUDED_PATH"
MANIFEST_UNAPPROVED_PATH = "MANIFEST_UNAPPROVED_PATH"
BOOTSTRAP_TOO_LARGE = "BOOTSTRAP_TOO_LARGE"
BOOTSTRAP_DECODE_ERROR = "BOOTSTRAP_DECODE_ERROR"
BOOTSTRAP_OUTSIDE_REPOSITORY_REFERENCE = "BOOTSTRAP_OUTSIDE_REPOSITORY_REFERENCE"
GZIP_NOT_FOUND = "GZIP_NOT_FOUND"
GZIP_NOT_REGULAR_FILE = "GZIP_NOT_REGULAR_FILE"
GZIP_COMPRESSED_SIZE_CAP_EXCEEDED = "GZIP_COMPRESSED_SIZE_CAP_EXCEEDED"
GZIP_DECOMPRESSED_SIZE_CAP_EXCEEDED = "GZIP_DECOMPRESSED_SIZE_CAP_EXCEEDED"
GZIP_CORRUPT = "GZIP_CORRUPT"
GZIP_LIMIT_CONFIGURATION_INVALID = "GZIP_LIMIT_CONFIGURATION_INVALID"
MYSQL_ENGINE_EVIDENCE_MISSING = "MYSQL_ENGINE_EVIDENCE_MISSING"
MYSQL_ENGINE_EVIDENCE_INVALID = "MYSQL_ENGINE_EVIDENCE_INVALID"
MYSQL_NON_TRANSACTIONAL_ENGINE_PRESENT = "MYSQL_NON_TRANSACTIONAL_ENGINE_PRESENT"
ATTESTATION_MALFORMED = "ATTESTATION_MALFORMED"
ATTESTATION_EXPIRED = "ATTESTATION_EXPIRED"
ATTESTATION_TIMESTAMP_INVALID = "ATTESTATION_TIMESTAMP_INVALID"
ATTESTATION_ARTIFACT_DIGEST_MISMATCH = "ATTESTATION_ARTIFACT_DIGEST_MISMATCH"
ATTESTATION_PROVENANCE_INSUFFICIENT = "ATTESTATION_PROVENANCE_INSUFFICIENT"
HOST_PATH_MAPPING_MISSING = "HOST_PATH_MAPPING_MISSING"
HOST_PATH_MAPPING_INVALID = "HOST_PATH_MAPPING_INVALID"
HOST_PATH_MAPPING_UNMAPPED_REFERENCE = "HOST_PATH_MAPPING_UNMAPPED_REFERENCE"
CRYPT_EVIDENCE_MISSING = "CRYPT_EVIDENCE_MISSING"
CRYPT_EVIDENCE_INVALID = "CRYPT_EVIDENCE_INVALID"
CRYPT_EVIDENCE_UNKNOWN_FIELD = "CRYPT_EVIDENCE_UNKNOWN_FIELD"
REPORT_ROOT_INVALID = "REPORT_ROOT_INVALID"
REPORT_ROOT_INSIDE_BACKUP_SCOPE = "REPORT_ROOT_INSIDE_BACKUP_SCOPE"
REPORT_PATH_SYMLINK_REJECTED = "REPORT_PATH_SYMLINK_REJECTED"
REPORT_WRITE_FAILED = "REPORT_WRITE_FAILED"

# ─── Allowed MySQL Engines ─────────────────────────────────────────────────────
ALLOWED_MYSQL_ENGINES: Set[str] = {
    "InnoDB", "MyISAM", "MEMORY", "CSV", "ARCHIVE",
    "BLACKHOLE", "NDB", "MERGE", "FEDERATED",
}

# ─── Allowed Crypt Evidence Fields ────────────────────────────────────────────
ALLOWED_CRYPT_FIELDS: Set[str] = {
    "REMOTE_NAME", "TYPE", "FILENAME_ENCRYPTION", "DIRECTORY_NAME_ENCRYPTION",
    "PASSWORD_VALUE_CAPTURED", "TOKEN_VALUE_CAPTURED",
}

# ─── Allowed Mapping Types ────────────────────────────────────────────────────
ALLOWED_MAPPING_TYPES: Set[str] = {
    "repository_artifact", "runtime_staging", "external_dependency", "manual_operator_step",
}

# ─── Report Section Field Allowlists ──────────────────────────────────────────
ALLOWED_MANIFEST_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "manifest_size_bytes", "nonblank_entry_count",
    "approved_entry_count", "excluded_entry_count", "unapproved_entry_count",
    "invalid_entry_count", "offending_entry_digest_count", "offending_entry_digests",
    "raw_manifest_sha256",
}

ALLOWED_BOOTSTRAP_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "bootstrap_size_bytes", "referenced_paths_checked",
    "repository_paths_verified", "referenced_units_checked", "repository_units_verified",
    "unresolved_reference_count", "outside_repository_reference_count",
    "raw_bootstrap_sha256",
}

ALLOWED_MYSQL_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "compressed_size_bytes", "decompressed_bytes_verified",
    "active_ddl_safety_established", "raw_dump_sha256", "gzip_stream_integrity_verified",
    "identity_stable_during_read",
}

ALLOWED_ATTESTATION_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "attestation_present", "attestation_digest_verified",
    "table_engine_counts",
}

ALLOWED_MAPPING_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "unmapped_reference_count", "mapped_references_verified",
}

ALLOWED_EXCLUDED_STORAGE_REPORT_FIELDS: Set[str] = {"status"}

ALLOWED_CRYPT_REPORT_FIELDS: Set[str] = {
    "status", "error_codes", "crypt_evidence_present", "crypt_type_verified",
    "filename_encryption_mode", "directory_name_encryption_enabled",
    "password_value_captured", "token_value_captured", "remote_identifier_digest",
}

ALLOWED_DR_DRILL_REPORT_FIELDS: Set[str] = {
    "status", "lab_plan_present", "no_touch_mount_list_present",
}


class ValidationStatus(str, enum.Enum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ─── Descriptor & Identity Helpers ────────────────────────────────────────────

def get_open_flags() -> int:
    """Returns required read-only open flags; fails closed if O_NOFOLLOW is missing."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError(PATH_SYMLINK_REJECTED)
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def capture_file_identity(st: os.stat_result) -> dict:
    """Captures file descriptor identity fields for pre/post read comparison."""
    return {
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "st_size": st.st_size,
        "st_mtime_ns": getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)),
    }


def compute_raw_sha256_and_identity(
    fd: int,
    *,
    max_bytes: int,
    chunk_size: int = 65536,
) -> dict:
    """
    Computes lower-case SHA-256 hex digest and captures pre/post descriptor identity
    from an already-open read-only regular file descriptor.
    """
    try:
        st_pre = os.fstat(fd)
        if not stat.S_ISREG(st_pre.st_mode):
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [PATH_NOT_REGULAR_FILE],
                "sha256": "",
                "byte_count": 0,
                "identity_stable_during_read": False,
                "identity": {},
            }

        if st_pre.st_size > max_bytes:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [MANIFEST_TOO_LARGE if max_bytes <= 64 * 1024 * 1024 else GZIP_COMPRESSED_SIZE_CAP_EXCEEDED],
                "sha256": "",
                "byte_count": st_pre.st_size,
                "identity_stable_during_read": False,
                "identity": {},
            }

        id_pre = capture_file_identity(st_pre)

        os.lseek(fd, 0, os.SEEK_SET)
        hasher = hashlib.sha256()
        total_read = 0

        while True:
            chunk = os.read(fd, min(chunk_size, 65536))
            if not chunk:
                break
            total_read += len(chunk)
            if total_read > max_bytes:
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [MANIFEST_TOO_LARGE if max_bytes <= 64 * 1024 * 1024 else GZIP_COMPRESSED_SIZE_CAP_EXCEEDED],
                    "sha256": "",
                    "byte_count": total_read,
                    "identity_stable_during_read": False,
                    "identity": id_pre,
                }
            hasher.update(chunk)

        st_post = os.fstat(fd)
        id_post = capture_file_identity(st_post)

        if id_pre != id_post:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [ARTIFACT_CHANGED_DURING_VALIDATION],
                "sha256": "",
                "byte_count": total_read,
                "identity_stable_during_read": False,
                "identity": id_pre,
            }

        return {
            "status": ValidationStatus.VERIFIED.value,
            "error_codes": [],
            "sha256": hasher.hexdigest(),
            "byte_count": total_read,
            "identity_stable_during_read": True,
            "identity": id_pre,
        }
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [PATH_NOT_FOUND],
            "sha256": "",
            "byte_count": 0,
            "identity_stable_during_read": False,
            "identity": {},
        }


# ─── Path Protection Helper ───────────────────────────────────────────────────

def require_controlled_path(
    candidate: Path,
    allowed_root: Path,
    *,
    must_exist: bool = True,
    allow_leaf_creation: bool = False,
) -> Path:
    """
    Validates that `candidate` is under `allowed_root` without symlink traversals.
    Applies ONLY to validator-controlled paths (files, directories, fixtures).
    """
    if not isinstance(candidate, Path):
        candidate = Path(candidate)
    if not isinstance(allowed_root, Path):
        allowed_root = Path(allowed_root)

    try:
        resolved_root = allowed_root.resolve(strict=True)
    except Exception:
        raise ValueError(PATH_OUTSIDE_ALLOWED_ROOT)

    if must_exist and not candidate.exists():
        raise ValueError(PATH_NOT_FOUND)

    check_target = candidate if candidate.exists() else candidate.parent
    try:
        current = check_target
        while current != current.parent:
            if current.exists():
                st = os.lstat(current)
                if stat.S_ISLNK(st.st_mode):
                    raise ValueError(PATH_SYMLINK_REJECTED)
            if current == resolved_root or current.parent == current:
                break
            current = current.parent
    except ValueError:
        raise
    except Exception:
        raise ValueError(PATH_SYMLINK_REJECTED)

    try:
        resolved_candidate = candidate.resolve(strict=must_exist)
    except Exception:
        raise ValueError(PATH_NOT_FOUND)

    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError:
        raise ValueError(PATH_OUTSIDE_ALLOWED_ROOT)

    return resolved_candidate


# ─── Manifest Validation ──────────────────────────────────────────────────────

def validate_manifest(
    manifest_path: Path,
    evidence_root: Path,
    approved_roots: Sequence[PurePosixPath],
    excluded_roots: Sequence[PurePosixPath],
    *,
    max_line_chars: int = 2048,
    max_entries: int = 100000,
    max_manifest_bytes: int = 64 * 1024 * 1024,
) -> dict:
    """
    Validates manifest entries as normalized POSIX path strings (NO live filesystem probing).
    Opens read-only with fstat regular file check, pre/post identity check, and byte caps.
    """
    error_codes: List[str] = []
    offending_digests: List[str] = []

    try:
        ctrl_path = require_controlled_path(manifest_path, evidence_root, must_exist=True)
        flags = get_open_flags()
    except ValueError as exc:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [str(exc)],
            "manifest_size_bytes": 0,
            "nonblank_entry_count": 0,
            "approved_entry_count": 0,
            "excluded_entry_count": 0,
            "unapproved_entry_count": 0,
            "invalid_entry_count": 0,
            "offending_entry_digest_count": 0,
            "offending_entry_digests": [],
            "raw_manifest_sha256": "",
        }

    try:
        fd = os.open(ctrl_path, flags)
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [PATH_NOT_FOUND],
            "manifest_size_bytes": 0,
            "nonblank_entry_count": 0,
            "approved_entry_count": 0,
            "excluded_entry_count": 0,
            "unapproved_entry_count": 0,
            "invalid_entry_count": 0,
            "offending_entry_digest_count": 0,
            "offending_entry_digests": [],
            "raw_manifest_sha256": "",
        }

    try:
        digest_info = compute_raw_sha256_and_identity(fd, max_bytes=max_manifest_bytes)
        if digest_info["status"] != ValidationStatus.VERIFIED.value:
            return {
                "status": digest_info["status"],
                "error_codes": digest_info["error_codes"],
                "manifest_size_bytes": digest_info["byte_count"],
                "nonblank_entry_count": 0,
                "approved_entry_count": 0,
                "excluded_entry_count": 0,
                "unapproved_entry_count": 0,
                "invalid_entry_count": 0,
                "offending_entry_digest_count": 0,
                "offending_entry_digests": [],
                "raw_manifest_sha256": "",
            }

        raw_sha256 = digest_info["sha256"]
        os.lseek(fd, 0, os.SEEK_SET)

        with os.fdopen(fd, "rb") as f:
            content = f.read()
            fd = -1

        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [MANIFEST_DECODE_ERROR],
            "manifest_size_bytes": digest_info["byte_count"] if 'digest_info' in locals() else 0,
            "nonblank_entry_count": 0,
            "approved_entry_count": 0,
            "excluded_entry_count": 0,
            "unapproved_entry_count": 0,
            "invalid_entry_count": 0,
            "offending_entry_digest_count": 0,
            "offending_entry_digests": [],
            "raw_manifest_sha256": "",
        }
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except Exception:
                pass

    lines = text.splitlines()
    nonblank_count = 0
    approved_count = 0
    excluded_count = 0
    unapproved_count = 0
    invalid_count = 0

    approved_posix = [PurePosixPath(p) for p in approved_roots]
    excluded_posix = [PurePosixPath(p) for p in excluded_roots]

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            continue

        nonblank_count += 1
        if nonblank_count > max_entries:
            error_codes.append(MANIFEST_ENTRY_LIMIT_EXCEEDED)
            break

        if len(line) > max_line_chars:
            invalid_count += 1
            if MANIFEST_LINE_TOO_LONG not in error_codes:
                error_codes.append(MANIFEST_LINE_TOO_LONG)
            continue

        if any(ord(c) < 32 for c in line):
            invalid_count += 1
            if MANIFEST_INVALID_ENTRY not in error_codes:
                error_codes.append(MANIFEST_INVALID_ENTRY)
            continue

        if not line.startswith("/") or line.startswith("//"):
            invalid_count += 1
            if MANIFEST_INVALID_ENTRY not in error_codes:
                error_codes.append(MANIFEST_INVALID_ENTRY)
            continue

        parts = line.split("/")
        if any(p == "" for p in parts[1:]) or any(p in (".", "..") for p in parts):
            invalid_count += 1
            if MANIFEST_INVALID_ENTRY not in error_codes:
                error_codes.append(MANIFEST_INVALID_ENTRY)
            digest = hashlib.sha256(f"adc-validation-manifest-entry-v1:{line}".encode("utf-8")).hexdigest()
            offending_digests.append(f"sha256:{digest}")
            continue

        entry_path = PurePosixPath(line)
        entry_parts = entry_path.parts

        is_excluded = False
        for ex in excluded_posix:
            ex_parts = ex.parts
            if len(entry_parts) >= len(ex_parts) and entry_parts[:len(ex_parts)] == ex_parts:
                is_excluded = True
                break

        if is_excluded:
            excluded_count += 1
            if MANIFEST_EXCLUDED_PATH not in error_codes:
                error_codes.append(MANIFEST_EXCLUDED_PATH)
            digest = hashlib.sha256(f"adc-validation-manifest-entry-v1:{line}".encode("utf-8")).hexdigest()
            offending_digests.append(f"sha256:{digest}")
            continue

        is_approved = False
        for app in approved_posix:
            app_parts = app.parts
            if len(entry_parts) >= len(app_parts) and entry_parts[:len(app_parts)] == app_parts:
                is_approved = True
                break

        if is_approved:
            approved_count += 1
        else:
            unapproved_count += 1
            if MANIFEST_UNAPPROVED_PATH not in error_codes:
                error_codes.append(MANIFEST_UNAPPROVED_PATH)
            digest = hashlib.sha256(f"adc-validation-manifest-entry-v1:{line}".encode("utf-8")).hexdigest()
            offending_digests.append(f"sha256:{digest}")

    sorted_digests = sorted(list(set(offending_digests)))[:20]

    if excluded_count > 0:
        status = ValidationStatus.BLOCKED.value
    elif invalid_count > 0 or unapproved_count > 0 or nonblank_count == 0 or approved_count == 0:
        status = ValidationStatus.NOT_VERIFIED.value
    elif MANIFEST_ENTRY_LIMIT_EXCEEDED in error_codes or MANIFEST_TOO_LARGE in error_codes:
        status = ValidationStatus.NOT_VERIFIED.value
    else:
        status = ValidationStatus.VERIFIED.value

    return {
        "status": status,
        "error_codes": list(set(error_codes)),
        "manifest_size_bytes": digest_info["byte_count"],
        "nonblank_entry_count": nonblank_count,
        "approved_entry_count": approved_count,
        "excluded_entry_count": excluded_count,
        "unapproved_entry_count": unapproved_count,
        "invalid_entry_count": invalid_count,
        "offending_entry_digest_count": len(offending_digests),
        "offending_entry_digests": sorted_digests,
        "raw_manifest_sha256": raw_sha256,
    }


# ─── Bootstrap Validation ─────────────────────────────────────────────────────

def validate_bootstrap(
    bootstrap_path: Path,
    repository_root: Path,
    *,
    max_bootstrap_bytes: int = 2 * 1024 * 1024,
) -> dict:
    """
    Inspects BOOTSTRAP.txt and checks repository-relative approved references only.
    Does NOT probe arbitrary host filesystem paths or run systemctl.
    """
    try:
        ctrl_repo = repository_root.resolve(strict=True)
        ctrl_boot = require_controlled_path(bootstrap_path, ctrl_repo, must_exist=True)
        flags = get_open_flags()
    except ValueError as exc:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [str(exc)],
            "bootstrap_size_bytes": 0,
            "referenced_paths_checked": 0,
            "repository_paths_verified": 0,
            "referenced_units_checked": 0,
            "repository_units_verified": 0,
            "unresolved_reference_count": 0,
            "outside_repository_reference_count": 0,
            "raw_bootstrap_sha256": "",
        }

    try:
        fd = os.open(ctrl_boot, flags)
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [PATH_NOT_FOUND],
            "bootstrap_size_bytes": 0,
            "referenced_paths_checked": 0,
            "repository_paths_verified": 0,
            "referenced_units_checked": 0,
            "repository_units_verified": 0,
            "unresolved_reference_count": 0,
            "outside_repository_reference_count": 0,
            "raw_bootstrap_sha256": "",
        }

    try:
        digest_info = compute_raw_sha256_and_identity(fd, max_bytes=max_bootstrap_bytes)
        if digest_info["status"] != ValidationStatus.VERIFIED.value:
            return {
                "status": digest_info["status"],
                "error_codes": digest_info["error_codes"],
                "bootstrap_size_bytes": digest_info["byte_count"],
                "referenced_paths_checked": 0,
                "repository_paths_verified": 0,
                "referenced_units_checked": 0,
                "repository_units_verified": 0,
                "unresolved_reference_count": 0,
                "outside_repository_reference_count": 0,
                "raw_bootstrap_sha256": "",
            }

        raw_sha256 = digest_info["sha256"]
        os.lseek(fd, 0, os.SEEK_SET)

        with os.fdopen(fd, "rb") as f:
            content = f.read()
            fd = -1

        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [BOOTSTRAP_DECODE_ERROR],
            "bootstrap_size_bytes": digest_info["byte_count"] if 'digest_info' in locals() else 0,
            "referenced_paths_checked": 0,
            "repository_paths_verified": 0,
            "referenced_units_checked": 0,
            "repository_units_verified": 0,
            "unresolved_reference_count": 0,
            "outside_repository_reference_count": 0,
            "raw_bootstrap_sha256": "",
        }
    finally:
        if fd != -1:
            try:
                os.close(fd)
            except Exception:
                pass

    error_codes: List[str] = []
    referenced_paths_checked = 0
    repository_paths_verified = 0
    referenced_units_checked = 0
    repository_units_verified = 0
    unresolved_count = 0
    outside_repo_count = 0

    path_refs = set(re.findall(r'/?(?:[\w.-]+/)+[\w.-]*', text))
    unit_refs = set(re.findall(r'[\w.-]+\.service', text))

    for ref in path_refs:
        if ref.startswith("/"):
            outside_repo_count += 1
            if BOOTSTRAP_OUTSIDE_REPOSITORY_REFERENCE not in error_codes:
                error_codes.append(BOOTSTRAP_OUTSIDE_REPOSITORY_REFERENCE)
            continue

        referenced_paths_checked += 1
        cand = ctrl_repo / ref
        try:
            require_controlled_path(cand, ctrl_repo, must_exist=True)
            repository_paths_verified += 1
        except Exception:
            unresolved_count += 1

    for unit in unit_refs:
        referenced_units_checked += 1
        cand_unit = ctrl_repo / "systemd" / unit
        try:
            require_controlled_path(cand_unit, ctrl_repo, must_exist=True)
            repository_units_verified += 1
        except Exception:
            unresolved_count += 1

    if outside_repo_count > 0 or unresolved_count > 0 or referenced_paths_checked == 0:
        status = ValidationStatus.NOT_VERIFIED.value
    else:
        status = ValidationStatus.VERIFIED.value

    return {
        "status": status,
        "error_codes": list(set(error_codes)),
        "bootstrap_size_bytes": digest_info["byte_count"],
        "referenced_paths_checked": referenced_paths_checked,
        "repository_paths_verified": repository_paths_verified,
        "referenced_units_checked": referenced_units_checked,
        "repository_units_verified": repository_units_verified,
        "unresolved_reference_count": unresolved_count,
        "outside_repository_reference_count": outside_repo_count,
        "raw_bootstrap_sha256": raw_sha256,
        "bootstrap_text": text,
    }


# ─── MySQL Dump Readiness ─────────────────────────────────────────────────────

def validate_mysql_readiness(
    dump_path: Path,
    evidence_root: Path,
    table_engine_counts: Mapping[str, int] | None,
    *,
    max_compressed_bytes: int,
    max_decompressed_bytes: int,
) -> dict:
    """
    Validates MySQL dump gzip integrity and engine metadata without opening database connections.
    Performs two controlled read-only passes with descriptor identity binding.
    """
    if max_compressed_bytes <= 0 or max_decompressed_bytes <= 0 or max_compressed_bytes > max_decompressed_bytes:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [GZIP_LIMIT_CONFIGURATION_INVALID],
            "compressed_size_bytes": 0,
            "decompressed_bytes_verified": 0,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": "",
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }

    try:
        ctrl_dump = require_controlled_path(dump_path, evidence_root, must_exist=True)
        flags = get_open_flags()
    except ValueError as exc:
        err = str(exc)
        return {
            "status": ValidationStatus.NOT_VERIFIED.value if err == PATH_NOT_FOUND else ValidationStatus.BLOCKED.value,
            "error_codes": [GZIP_NOT_FOUND if err == PATH_NOT_FOUND else err],
            "compressed_size_bytes": 0,
            "decompressed_bytes_verified": 0,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": "",
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }

    # Pass 1: Raw byte SHA-256 calculation & identity check
    try:
        fd1 = os.open(ctrl_dump, flags)
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [GZIP_NOT_FOUND],
            "compressed_size_bytes": 0,
            "decompressed_bytes_verified": 0,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": "",
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }

    try:
        pass1_info = compute_raw_sha256_and_identity(fd1, max_bytes=max_compressed_bytes)
    finally:
        try:
            os.close(fd1)
        except Exception:
            pass

    if pass1_info["status"] != ValidationStatus.VERIFIED.value:
        return {
            "status": pass1_info["status"],
            "error_codes": pass1_info["error_codes"],
            "compressed_size_bytes": pass1_info["byte_count"],
            "decompressed_bytes_verified": 0,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": "",
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }

    raw_sha256 = pass1_info["sha256"]
    pass1_identity = pass1_info["identity"]

    # Pass 2: Reopen safely, compare identity, stream GzipFile
    try:
        fd2 = os.open(ctrl_dump, flags)
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [GZIP_NOT_FOUND],
            "compressed_size_bytes": pass1_info["byte_count"],
            "decompressed_bytes_verified": 0,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": raw_sha256,
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }

    decompressed_bytes = 0
    try:
        st_pass2_pre = os.fstat(fd2)
        id_pass2_pre = capture_file_identity(st_pass2_pre)

        if id_pass2_pre != pass1_identity:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [ARTIFACT_IDENTITY_MISMATCH],
                "compressed_size_bytes": st_pass2_pre.st_size,
                "decompressed_bytes_verified": 0,
                "active_ddl_safety_established": False,
                "raw_dump_sha256": raw_sha256,
                "gzip_stream_integrity_verified": False,
                "identity_stable_during_read": False,
            }

        with os.fdopen(fd2, "rb") as f_raw:
            fd2 = -1
            with gzip.GzipFile(fileobj=f_raw, mode="rb") as gz:
                while True:
                    chunk = gz.read(65536)
                    if not chunk:
                        break
                    decompressed_bytes += len(chunk)
                    if decompressed_bytes > max_decompressed_bytes:
                        return {
                            "status": ValidationStatus.NOT_VERIFIED.value,
                            "error_codes": [GZIP_DECOMPRESSED_SIZE_CAP_EXCEEDED],
                            "compressed_size_bytes": st_pass2_pre.st_size,
                            "decompressed_bytes_verified": decompressed_bytes,
                            "active_ddl_safety_established": False,
                            "raw_dump_sha256": raw_sha256,
                            "gzip_stream_integrity_verified": False,
                            "identity_stable_during_read": False,
                        }

        st_pass2_post = os.fstat(f_raw.fileno() if not f_raw.closed else os.open(ctrl_dump, flags))
        id_pass2_post = capture_file_identity(st_pass2_post)

        if id_pass2_pre != id_pass2_post:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [ARTIFACT_CHANGED_DURING_VALIDATION],
                "compressed_size_bytes": st_pass2_pre.st_size,
                "decompressed_bytes_verified": decompressed_bytes,
                "active_ddl_safety_established": False,
                "raw_dump_sha256": raw_sha256,
                "gzip_stream_integrity_verified": False,
                "identity_stable_during_read": False,
            }
    except Exception:
        return {
            "status": ValidationStatus.BLOCKED.value,
            "error_codes": [GZIP_CORRUPT],
            "compressed_size_bytes": st_pass2_pre.st_size if 'st_pass2_pre' in locals() else 0,
            "decompressed_bytes_verified": decompressed_bytes,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": raw_sha256,
            "gzip_stream_integrity_verified": False,
            "identity_stable_during_read": False,
        }
    finally:
        if fd2 != -1:
            try:
                os.close(fd2)
            except Exception:
                pass

    # Validate table engine evidence
    if table_engine_counts is None:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [MYSQL_ENGINE_EVIDENCE_MISSING],
            "compressed_size_bytes": st_pass2_pre.st_size,
            "decompressed_bytes_verified": decompressed_bytes,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": raw_sha256,
            "gzip_stream_integrity_verified": True,
            "identity_stable_during_read": True,
        }

    if not isinstance(table_engine_counts, Mapping):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [MYSQL_ENGINE_EVIDENCE_INVALID],
            "compressed_size_bytes": st_pass2_pre.st_size,
            "decompressed_bytes_verified": decompressed_bytes,
            "active_ddl_safety_established": False,
            "raw_dump_sha256": raw_sha256,
            "gzip_stream_integrity_verified": True,
            "identity_stable_during_read": True,
        }

    for k, v in table_engine_counts.items():
        if not isinstance(k, str) or k not in ALLOWED_MYSQL_ENGINES:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [MYSQL_ENGINE_EVIDENCE_INVALID],
                "compressed_size_bytes": st_pass2_pre.st_size,
                "decompressed_bytes_verified": decompressed_bytes,
                "active_ddl_safety_established": False,
                "raw_dump_sha256": raw_sha256,
                "gzip_stream_integrity_verified": True,
                "identity_stable_during_read": True,
            }
        if type(v) is not int or v < 0:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [MYSQL_ENGINE_EVIDENCE_INVALID],
                "compressed_size_bytes": st_pass2_pre.st_size,
                "decompressed_bytes_verified": decompressed_bytes,
                "active_ddl_safety_established": False,
                "raw_dump_sha256": raw_sha256,
                "gzip_stream_integrity_verified": True,
                "identity_stable_during_read": True,
            }

    non_innodb = (table_engine_counts.get("MyISAM", 0) > 0) or (table_engine_counts.get("MEMORY", 0) > 0)
    innodb_count = table_engine_counts.get("InnoDB", 0)

    if non_innodb:
        status = ValidationStatus.WARNING.value
        errs = [MYSQL_NON_TRANSACTIONAL_ENGINE_PRESENT]
    elif innodb_count > 0:
        status = ValidationStatus.VERIFIED.value
        errs = []
    else:
        status = ValidationStatus.NOT_VERIFIED.value
        errs = [MYSQL_ENGINE_EVIDENCE_INVALID]

    return {
        "status": status,
        "error_codes": errs,
        "compressed_size_bytes": st_pass2_pre.st_size,
        "decompressed_bytes_verified": decompressed_bytes,
        "active_ddl_safety_established": False,
        "raw_dump_sha256": raw_sha256,
        "gzip_stream_integrity_verified": True,
        "identity_stable_during_read": True,
    }


# ─── Engine Attestation Validation ───────────────────────────────────────────

def validate_engine_attestation(
    attestation: Mapping[str, object] | None,
    *,
    computed_dump_sha256: str | None,
    now_utc: datetime,
    max_age: timedelta,
) -> dict:
    """
    Validates digest-bound table-engine attestation schema (engine_attestation_v1).
    """
    if attestation is None or not isinstance(attestation, Mapping):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_MALFORMED],
            "attestation_present": False,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    schema_version = attestation.get("schema_version")
    if schema_version != "engine_attestation_v1":
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_MALFORMED],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    provenance = attestation.get("provenance_status")
    if provenance != "OPERATOR_PROVIDED_NOT_INDEPENDENTLY_VERIFIED":
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_PROVENANCE_INSUFFICIENT],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    ts_str = attestation.get("attestation_timestamp_utc")
    if not isinstance(ts_str, str):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_TIMESTAMP_INVALID],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    try:
        ts_clean = ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str
        att_ts = datetime.fromisoformat(ts_clean)
        if att_ts.tzinfo is None:
            att_ts = att_ts.replace(tzinfo=timezone.utc)
    except Exception:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_TIMESTAMP_INVALID],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    if att_ts > now_utc or (now_utc - att_ts) > max_age:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_EXPIRED],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    dump_sha256 = attestation.get("dump_artifact_sha256")
    if not isinstance(dump_sha256, str) or not re.match(r"^[0-9a-f]{64}$", dump_sha256, re.IGNORECASE):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_MALFORMED],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    if computed_dump_sha256 is not None and computed_dump_sha256 != "":
        clean_computed = computed_dump_sha256.lower().replace("sha256:", "")
        if dump_sha256.lower() != clean_computed:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [ATTESTATION_ARTIFACT_DIGEST_MISMATCH],
                "attestation_present": True,
                "attestation_digest_verified": False,
                "table_engine_counts": {},
            }

    counts = attestation.get("table_engine_counts")
    if not isinstance(counts, Mapping):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [ATTESTATION_MALFORMED],
            "attestation_present": True,
            "attestation_digest_verified": False,
            "table_engine_counts": {},
        }

    for k, v in counts.items():
        if not isinstance(k, str) or k not in ALLOWED_MYSQL_ENGINES or type(v) is not int or v < 0:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [ATTESTATION_MALFORMED],
                "attestation_present": True,
                "attestation_digest_verified": False,
                "table_engine_counts": {},
            }

    non_innodb = (counts.get("MyISAM", 0) > 0) or (counts.get("MEMORY", 0) > 0)
    innodb_count = counts.get("InnoDB", 0)

    if non_innodb:
        status = ValidationStatus.WARNING.value
        errs = [MYSQL_NON_TRANSACTIONAL_ENGINE_PRESENT]
    elif innodb_count > 0:
        status = ValidationStatus.VERIFIED.value
        errs = []
    else:
        status = ValidationStatus.NOT_VERIFIED.value
        errs = [ATTESTATION_MALFORMED]

    return {
        "status": status,
        "error_codes": errs,
        "attestation_present": True,
        "attestation_digest_verified": True,
        "table_engine_counts": dict(counts),
    }


# ─── Host Path Mapping Validation ────────────────────────────────────────────

def validate_host_path_mappings(
    mapping_data: Mapping[str, object] | None,
    bootstrap_text: str | None,
    repository_root: Path,
) -> dict:
    """
    Validates host-path mapping schema (host_path_map_v1) against BOOTSTRAP.txt references.
    """
    if mapping_data is None or not isinstance(mapping_data, Mapping):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [HOST_PATH_MAPPING_MISSING],
            "unmapped_reference_count": 0,
            "mapped_references_verified": 0,
        }

    if mapping_data.get("schema_version") != "host_path_map_v1":
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [HOST_PATH_MAPPING_INVALID],
            "unmapped_reference_count": 0,
            "mapped_references_verified": 0,
        }

    mappings_list = mapping_data.get("mappings")
    if not isinstance(mappings_list, Sequence) or isinstance(mappings_list, (str, bytes)):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [HOST_PATH_MAPPING_INVALID],
            "unmapped_reference_count": 0,
            "mapped_references_verified": 0,
        }

    discovered_abs_paths: Set[str] = set()
    if bootstrap_text:
        path_refs = re.findall(r'/(?:[\w.-]+/)+[\w.-]*', bootstrap_text)
        discovered_abs_paths = {p.rstrip("/") for p in path_refs if p.startswith("/")}

    mapped_table: Dict[str, dict] = {}
    for entry in mappings_list:
        if not isinstance(entry, Mapping):
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [HOST_PATH_MAPPING_INVALID],
                "unmapped_reference_count": 0,
                "mapped_references_verified": 0,
            }

        ref = entry.get("host_path_reference")
        m_type = entry.get("mapping_type")

        if not isinstance(ref, str) or not ref.startswith("/"):
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [HOST_PATH_MAPPING_INVALID],
                "unmapped_reference_count": 0,
                "mapped_references_verified": 0,
            }

        if m_type not in ALLOWED_MAPPING_TYPES:
            return {
                "status": ValidationStatus.NOT_VERIFIED.value,
                "error_codes": [HOST_PATH_MAPPING_INVALID],
                "unmapped_reference_count": 0,
                "mapped_references_verified": 0,
            }

        clean_ref = ref.rstrip("/")
        if m_type == "repository_artifact":
            target = entry.get("repository_relative_target")
            if not isinstance(target, str) or target.startswith("/") or ".." in target:
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [HOST_PATH_MAPPING_INVALID],
                    "unmapped_reference_count": 0,
                    "mapped_references_verified": 0,
                }
            cand = repository_root / target
            try:
                require_controlled_path(cand, repository_root, must_exist=True)
            except Exception:
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [HOST_PATH_MAPPING_INVALID],
                    "unmapped_reference_count": 0,
                    "mapped_references_verified": 0,
                }
        elif m_type == "runtime_staging":
            if entry.get("repository_relative_target") is not None:
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [HOST_PATH_MAPPING_INVALID],
                    "unmapped_reference_count": 0,
                    "mapped_references_verified": 0,
                }
            if entry.get("restore_write_authorization") != "LAB_ONLY":
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [HOST_PATH_MAPPING_INVALID],
                    "unmapped_reference_count": 0,
                    "mapped_references_verified": 0,
                }
            if clean_ref in ("", "/var/www", "/etc", "/root", "/opt/adc"):
                return {
                    "status": ValidationStatus.NOT_VERIFIED.value,
                    "error_codes": [HOST_PATH_MAPPING_INVALID],
                    "unmapped_reference_count": 0,
                    "mapped_references_verified": 0,
                }

        mapped_table[clean_ref] = dict(entry)

    unmapped_count = 0
    mapped_verified_count = 0

    for abs_path in discovered_abs_paths:
        if abs_path in mapped_table:
            mapped_verified_count += 1
        else:
            unmapped_count += 1

    if unmapped_count > 0:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [HOST_PATH_MAPPING_UNMAPPED_REFERENCE],
            "unmapped_reference_count": unmapped_count,
            "mapped_references_verified": mapped_verified_count,
        }

    return {
        "status": ValidationStatus.VERIFIED.value,
        "error_codes": [],
        "unmapped_reference_count": 0,
        "mapped_references_verified": mapped_verified_count,
    }


# ─── Crypt Evidence Validation ────────────────────────────────────────────────

def validate_rclone_crypt(crypt_evidence: Mapping[str, object] | None) -> dict:
    """
    Validates sanitized operator evidence for rclone crypt settings without invoking rclone.
    """
    if crypt_evidence is None:
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [CRYPT_EVIDENCE_MISSING],
            "crypt_evidence_present": False,
            "crypt_type_verified": False,
            "filename_encryption_mode": "unknown",
            "directory_name_encryption_enabled": False,
            "password_value_captured": False,
            "token_value_captured": False,
            "remote_identifier_digest": "none",
        }

    if not isinstance(crypt_evidence, Mapping):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [CRYPT_EVIDENCE_INVALID],
            "crypt_evidence_present": False,
            "crypt_type_verified": False,
            "filename_encryption_mode": "unknown",
            "directory_name_encryption_enabled": False,
            "password_value_captured": False,
            "token_value_captured": False,
            "remote_identifier_digest": "none",
        }

    keys = set(crypt_evidence.keys())
    if keys != ALLOWED_CRYPT_FIELDS:
        err = CRYPT_EVIDENCE_UNKNOWN_FIELD if (keys - ALLOWED_CRYPT_FIELDS) else CRYPT_EVIDENCE_INVALID
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [err],
            "crypt_evidence_present": True,
            "crypt_type_verified": False,
            "filename_encryption_mode": "unknown",
            "directory_name_encryption_enabled": False,
            "password_value_captured": False,
            "token_value_captured": False,
            "remote_identifier_digest": "none",
        }

    remote_name = crypt_evidence["REMOTE_NAME"]
    ctype = crypt_evidence["TYPE"]
    fname_enc = crypt_evidence["FILENAME_ENCRYPTION"]
    dname_enc = crypt_evidence["DIRECTORY_NAME_ENCRYPTION"]
    pass_cap = crypt_evidence["PASSWORD_VALUE_CAPTURED"]
    tok_cap = crypt_evidence["TOKEN_VALUE_CAPTURED"]

    if not isinstance(remote_name, str) or not re.match(r"^[A-Za-z0-9_-]{1,64}$", remote_name):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [CRYPT_EVIDENCE_INVALID],
            "crypt_evidence_present": True,
            "crypt_type_verified": False,
            "filename_encryption_mode": "unknown",
            "directory_name_encryption_enabled": False,
            "password_value_captured": False,
            "token_value_captured": False,
            "remote_identifier_digest": "none",
        }

    if ctype != "crypt" or fname_enc not in ("standard", "obfuscate", "off"):
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [CRYPT_EVIDENCE_INVALID],
            "crypt_evidence_present": True,
            "crypt_type_verified": False,
            "filename_encryption_mode": str(fname_enc),
            "directory_name_encryption_enabled": False,
            "password_value_captured": False,
            "token_value_captured": False,
            "remote_identifier_digest": "none",
        }

    if type(dname_enc) is not bool or pass_cap != "NO" or tok_cap != "NO":
        return {
            "status": ValidationStatus.NOT_VERIFIED.value,
            "error_codes": [CRYPT_EVIDENCE_INVALID],
            "crypt_evidence_present": True,
            "crypt_type_verified": True,
            "filename_encryption_mode": str(fname_enc),
            "directory_name_encryption_enabled": bool(dname_enc),
            "password_value_captured": True if pass_cap != "NO" else False,
            "token_value_captured": True if tok_cap != "NO" else False,
            "remote_identifier_digest": "none",
        }

    digest = hashlib.sha256(f"adc-validation-crypt-remote-v1:{remote_name}".encode("utf-8")).hexdigest()

    return {
        "status": ValidationStatus.VERIFIED.value,
        "error_codes": [],
        "crypt_evidence_present": True,
        "crypt_type_verified": True,
        "filename_encryption_mode": fname_enc,
        "directory_name_encryption_enabled": dname_enc,
        "password_value_captured": False,
        "token_value_captured": False,
        "remote_identifier_digest": f"sha256:{digest[:16]}",
    }


# ─── DR Readiness Evaluation ──────────────────────────────────────────────────

def evaluate_dr_readiness(
    *,
    manifest_validation: Mapping[str, object],
    bootstrap_alignment: Mapping[str, object],
    mysql_restore_readiness: Mapping[str, object],
    rclone_crypt_evidence: Mapping[str, object],
    attestation_validation: Mapping[str, object] | None = None,
    host_path_mapping_validation: Mapping[str, object] | None = None,
    lab_plan_present: bool = False,
    no_touch_mount_list_present: bool = False,
) -> dict:
    """
    Evaluates DR drill readiness and overall GO / NO_GO decision.
    """
    m_status = manifest_validation.get("status", ValidationStatus.NOT_VERIFIED.value)
    b_status = bootstrap_alignment.get("status", ValidationStatus.NOT_VERIFIED.value)
    db_status = mysql_restore_readiness.get("status", ValidationStatus.NOT_VERIFIED.value)
    c_status = rclone_crypt_evidence.get("status", ValidationStatus.NOT_VERIFIED.value)
    att_status = (attestation_validation or {}).get("status", ValidationStatus.VERIFIED.value if attestation_validation is None else ValidationStatus.NOT_VERIFIED.value)
    map_status = (host_path_mapping_validation or {}).get("status", ValidationStatus.VERIFIED.value if host_path_mapping_validation is None else ValidationStatus.NOT_VERIFIED.value)

    if m_status == ValidationStatus.BLOCKED.value:
        ex_protection = ValidationStatus.BLOCKED.value
    elif m_status == ValidationStatus.VERIFIED.value:
        ex_protection = ValidationStatus.VERIFIED.value
    else:
        ex_protection = ValidationStatus.NOT_VERIFIED.value

    dr_ready = (
        lab_plan_present
        and no_touch_mount_list_present
        and m_status == ValidationStatus.VERIFIED.value
        and b_status == ValidationStatus.VERIFIED.value
        and db_status == ValidationStatus.VERIFIED.value
        and c_status == ValidationStatus.VERIFIED.value
        and att_status == ValidationStatus.VERIFIED.value
        and map_status == ValidationStatus.VERIFIED.value
    )

    dr_status = ValidationStatus.VERIFIED.value if dr_ready else ValidationStatus.NOT_VERIFIED.value
    overall_go_no_go = "GO" if dr_ready else "NO_GO"

    res = {
        "manifest_validation": dict(manifest_validation),
        "bootstrap_alignment": dict(bootstrap_alignment),
        "mysql_restore_readiness": dict(mysql_restore_readiness),
        "excluded_storage_protection": {"status": ex_protection},
        "rclone_crypt_evidence": dict(rclone_crypt_evidence),
        "dr_drill_readiness": {
            "status": dr_status,
            "lab_plan_present": lab_plan_present,
            "no_touch_mount_list_present": no_touch_mount_list_present,
        },
        "overall_go_no_go": overall_go_no_go,
    }

    if attestation_validation is not None:
        res["engine_attestation"] = dict(attestation_validation)
    if host_path_mapping_validation is not None:
        res["host_path_mappings"] = dict(host_path_mapping_validation)

    return res


# ─── Report Serializer ────────────────────────────────────────────────────────

def _filter_dict(data: Mapping[str, object], allowed_fields: Set[str]) -> dict:
    """Filters dictionary keys against explicit field allowlist."""
    if not isinstance(data, Mapping):
        return {}
    return {k: v for k, v in data.items() if k in allowed_fields}


def generate_validation_report(
    results: Mapping[str, object],
    scratch_root: Path,
    backup_source_roots: Sequence[Path],
) -> dict:
    """
    Atomically writes sanitized validation_report.json, validation_report.md,
    and evidence_manifest.json with mode 0600 in scratch_root/validation/.
    Refuses writing if scratch_root resolves inside any backup source root or contains symlink components.
    """
    if not isinstance(scratch_root, Path):
        scratch_root = Path(scratch_root)

    try:
        current = scratch_root
        while current != current.parent:
            if current.exists() and stat.S_ISLNK(os.lstat(current).st_mode):
                return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_PATH_SYMLINK_REJECTED]}
            current = current.parent
        resolved_scratch = scratch_root.resolve(strict=True)
    except Exception:
        return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_ROOT_INVALID]}

    for s_root in backup_source_roots:
        try:
            res_s = Path(s_root).resolve(strict=True)
            try:
                resolved_scratch.relative_to(res_s)
                return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_ROOT_INSIDE_BACKUP_SCOPE]}
            except ValueError:
                pass
        except Exception:
            return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_ROOT_INSIDE_BACKUP_SCOPE]}

    val_dir = scratch_root / "validation"
    if val_dir.exists():
        if stat.S_ISLNK(os.lstat(val_dir).st_mode):
            return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_PATH_SYMLINK_REJECTED]}
    else:
        val_dir.mkdir(parents=True, mode=0o700, exist_ok=True)

    json_dest = val_dir / "validation_report.json"
    md_dest = val_dir / "validation_report.md"
    ev_dest = val_dir / "evidence_manifest.json"

    if (json_dest.exists() and stat.S_ISLNK(os.lstat(json_dest).st_mode)) or \
       (md_dest.exists() and stat.S_ISLNK(os.lstat(md_dest).st_mode)) or \
       (ev_dest.exists() and stat.S_ISLNK(os.lstat(ev_dest).st_mode)):
        return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_PATH_SYMLINK_REJECTED]}

    m_val = results.get("manifest_validation", {})
    b_val = results.get("bootstrap_alignment", {})
    db_val = results.get("mysql_restore_readiness", {})

    sanitized_payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "overall_go_no_go": results.get("overall_go_no_go", "NO_GO") if results.get("overall_go_no_go") in ("GO", "NO_GO") else "NO_GO",
        "manifest_validation": _filter_dict(m_val, ALLOWED_MANIFEST_REPORT_FIELDS),
        "bootstrap_alignment": _filter_dict(b_val, ALLOWED_BOOTSTRAP_REPORT_FIELDS),
        "mysql_restore_readiness": _filter_dict(db_val, ALLOWED_MYSQL_REPORT_FIELDS),
        "excluded_storage_protection": _filter_dict(results.get("excluded_storage_protection", {}), ALLOWED_EXCLUDED_STORAGE_REPORT_FIELDS),
        "rclone_crypt_evidence": _filter_dict(results.get("rclone_crypt_evidence", {}), ALLOWED_CRYPT_REPORT_FIELDS),
        "dr_drill_readiness": _filter_dict(results.get("dr_drill_readiness", {}), ALLOWED_DR_DRILL_REPORT_FIELDS),
    }

    if "engine_attestation" in results:
        sanitized_payload["engine_attestation"] = _filter_dict(results["engine_attestation"], ALLOWED_ATTESTATION_REPORT_FIELDS)
    if "host_path_mappings" in results:
        sanitized_payload["host_path_mappings"] = _filter_dict(results["host_path_mappings"], ALLOWED_MAPPING_REPORT_FIELDS)

    evidence_manifest_payload = {
        "schema_version": "adc_evidence_manifest_v1",
        "package_created_at_utc": sanitized_payload["timestamp_utc"],
        "validator_version": "1.1.0-phase0.1",
        "input_artifacts_read_in_place": True,
        "raw_artifacts_copied_to_evidence_root": False,
        "report_root_external_to_backup_scope": True,
        "report_file_mode": "0600",
        "report_directory_mode": "0700",
        "artifact_digests": {
            "manifest_file": m_val.get("raw_manifest_sha256", ""),
            "gzip_dump_artifact": db_val.get("raw_dump_sha256", ""),
            "bootstrap_file": b_val.get("raw_bootstrap_sha256", ""),
        },
    }

    json_text = json.dumps(sanitized_payload, indent=2, sort_keys=True) + "\n"
    ev_text = json.dumps(evidence_manifest_payload, indent=2, sort_keys=True) + "\n"
    md_text = f"""# CloudBackup for Windows — Disaster Recovery Readiness Audit Report


- **Report Timestamp**: {sanitized_payload['timestamp_utc']}
- **Overall DR Drill Status**: `{sanitized_payload['overall_go_no_go']}`

## Subsystem Validation Statuses

- **Manifest Scope & Exclusion**: `{sanitized_payload['manifest_validation'].get('status', 'NOT_VERIFIED')}`
- **Bootstrap Alignment**: `{sanitized_payload['bootstrap_alignment'].get('status', 'NOT_VERIFIED')}`
- **MySQL Restore Readiness**: `{sanitized_payload['mysql_restore_readiness'].get('status', 'NOT_VERIFIED')}`
- **Excluded Storage Protection**: `{sanitized_payload['excluded_storage_protection'].get('status', 'NOT_VERIFIED')}`
- **Rclone Crypt Evidence**: `{sanitized_payload['rclone_crypt_evidence'].get('status', 'NOT_VERIFIED')}`
- **DR Drill Lab Readiness**: `{sanitized_payload['dr_drill_readiness'].get('status', 'NOT_VERIFIED')}`
"""

    try:
        flags_write = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_CLOEXEC"):
            flags_write |= os.O_CLOEXEC

        # Write JSON
        tmp_json = val_dir / f".tmp_report_{os.getpid()}_json.tmp"
        fd = os.open(tmp_json, flags_write, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json_text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_json, json_dest)

        # Write Evidence Manifest JSON
        tmp_ev = val_dir / f".tmp_report_{os.getpid()}_ev.tmp"
        fd_ev = os.open(tmp_ev, flags_write, 0o600)
        with os.fdopen(fd_ev, "w", encoding="utf-8") as f:
            f.write(ev_text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_ev, ev_dest)

        # Write MD
        tmp_md = val_dir / f".tmp_report_{os.getpid()}_md.tmp"
        fd_md = os.open(tmp_md, flags_write, 0o600)
        with os.fdopen(fd_md, "w", encoding="utf-8") as f:
            f.write(md_text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_md, md_dest)

        os.chmod(json_dest, 0o600)
        os.chmod(ev_dest, 0o600)
        os.chmod(md_dest, 0o600)
        os.chmod(val_dir, 0o700)

        return {
            "status": ValidationStatus.VERIFIED.value,
            "error_codes": [],
            "json_report_path": str(json_dest),
            "md_report_path": str(md_dest),
            "evidence_manifest_path": str(ev_dest),
        }
    except Exception:
        return {"status": ValidationStatus.NOT_VERIFIED.value, "error_codes": [REPORT_WRITE_FAILED]}
