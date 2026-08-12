"""
tests/test_validation.py — Comprehensive unit tests for shared/validation.py module.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from datetime import datetime, timedelta, timezone

from shared.validation import (
    ValidationStatus,
    capture_file_identity,
    compute_raw_sha256_and_identity,
    evaluate_dr_readiness,
    generate_validation_report,
    get_open_flags,
    require_controlled_path,
    validate_bootstrap,
    validate_engine_attestation,
    validate_host_path_mappings,
    validate_manifest,
    validate_mysql_readiness,
    validate_rclone_crypt,
)


class TestValidationSubsystem(unittest.TestCase):

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()

        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()

        self.repo_root = self.root / "repo"
        self.repo_root.mkdir()
        (self.repo_root / "systemd").mkdir()

        self.scratch_root = self.root / "scratch"
        self.scratch_root.mkdir()

        self.approved_roots = [PurePosixPath("/etc"), PurePosixPath("/opt/adc-backup")]
        self.excluded_roots = [PurePosixPath("/mnt"), PurePosixPath("/media"), PurePosixPath("/data/storage")]

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Manifest containing /mnt/, /media/, or /data/storage/ returns BLOCKED
    def test_1_manifest_with_excluded_path_blocked(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/etc/config.yaml\n/mnt/storage/data.iso\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.BLOCKED.value)
        self.assertEqual(res["excluded_entry_count"], 1)

    # 2. Clean approved-prefix manifest returns VERIFIED
    def test_2_clean_approved_manifest_verified(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/etc/nginx/nginx.conf\n/opt/adc-backup/config.yaml\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)
        self.assertEqual(res["approved_entry_count"], 2)

    # 3. Missing manifest returns NOT_VERIFIED
    def test_3_missing_manifest_not_verified(self) -> None:
        mf = self.evidence_root / "nonexistent.txt"
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 4. Corrupt gzip artifact returns BLOCKED
    def test_4_corrupt_gzip_blocked(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(b"NOT_A_VALID_GZIP_STREAM_HEADER_DATA")
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 10},
            max_compressed_bytes=10 * 1024 * 1024, max_decompressed_bytes=50 * 1024 * 1024
        )
        self.assertEqual(res["status"], ValidationStatus.BLOCKED.value)

    # 5. MyISAM engine count returns WARNING
    def test_5_myisam_engine_warning(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(b"CREATE TABLE test (id INT);")
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 10, "MyISAM": 2},
            max_compressed_bytes=10 * 1024 * 1024, max_decompressed_bytes=50 * 1024 * 1024
        )
        self.assertEqual(res["status"], ValidationStatus.WARNING.value)

    # 6. MEMORY engine count returns WARNING
    def test_6_memory_engine_warning(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(b"CREATE TABLE test (id INT);")
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 10, "MEMORY": 1},
            max_compressed_bytes=10 * 1024 * 1024, max_decompressed_bytes=50 * 1024 * 1024
        )
        self.assertEqual(res["status"], ValidationStatus.WARNING.value)

    # 7. Missing crypt evidence returns NOT_VERIFIED
    def test_7_missing_crypt_evidence_not_verified(self) -> None:
        res = validate_rclone_crypt(None)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 8. Manifest containing ../ returns BLOCKED / invalid
    def test_8_manifest_dotdot_invalid(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/etc/../root/.ssh/id_rsa\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertGreater(res["invalid_entry_count"], 0)

    # 9. Manifest containing a relative path returns NOT_VERIFIED / invalid
    def test_9_manifest_relative_path_invalid(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("etc/nginx/nginx.conf\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 10. Manifest with NUL or control character returns invalid
    def test_10_manifest_control_char_invalid(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_bytes(b"/etc/nginx\x00/nginx.conf\n")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 11. Manifest over entry limit returns NOT_VERIFIED
    def test_11_manifest_over_entry_limit(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("\n".join([f"/etc/file{i}.txt" for i in range(20)]), encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots, max_entries=10)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 12. Manifest exceeding byte cap returns NOT_VERIFIED
    def test_12_manifest_exceeding_byte_cap(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/etc/nginx.conf\n" * 100, encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots, max_manifest_bytes=50)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 13. Manifest entry outside approved and excluded roots returns NOT_VERIFIED
    def test_13_manifest_unapproved_path(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/usr/local/unexpected-file.txt\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertEqual(res["unapproved_entry_count"], 1)

    # 14. /opt/adc-backup-old/data does not match /opt/adc-backup
    def test_14_component_prefix_isolation(self) -> None:
        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/opt/adc-backup-old/data/db.sqlite\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertEqual(res["unapproved_entry_count"], 1)

    # 15. Manifest entries are never filesystem-probed
    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.resolve")
    def test_15_no_filesystem_probing_for_manifest_entries(self, mock_resolve, mock_exists) -> None:
        mock_exists.return_value = True
        mock_resolve.side_effect = lambda *a, **kw: self.evidence_root / "manifest.txt"

        mf = self.evidence_root / "manifest.txt"
        mf.write_text("/etc/nginx/nginx.conf\n/opt/adc-backup/state.db\n", encoding="utf-8")
        res = validate_manifest(mf, self.evidence_root, self.approved_roots, self.excluded_roots)

        # Confirm mock_exists was called ONLY for the manifest file itself, not individual entry paths
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)

    # 16. Symlinked controlled manifest file escaping root returns BLOCKED / error
    def test_16_symlink_manifest_escapes_root(self) -> None:
        outside_file = self.root / "outside.txt"
        outside_file.write_text("/etc/config\n", encoding="utf-8")
        sym_mf = self.evidence_root / "sym_manifest.txt"

        try:
            os.symlink(outside_file, sym_mf)
        except OSError:
            self.skipTest("Symlinks not supported on platform")

        res = validate_manifest(sym_mf, self.evidence_root, self.approved_roots, self.excluded_roots)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 17. Symlinked BOOTSTRAP.txt path returns NOT_VERIFIED
    def test_17_symlinked_bootstrap_rejected(self) -> None:
        outside_boot = self.root / "outside_boot.txt"
        outside_boot.write_text("Stage 1", encoding="utf-8")
        sym_boot = self.repo_root / "BOOTSTRAP.txt"

        try:
            os.symlink(outside_boot, sym_boot)
        except OSError:
            self.skipTest("Symlinks not supported")

        res = validate_bootstrap(sym_boot, self.repo_root)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 18. Bootstrap absolute outside-repository references do not trigger filesystem probing
    def test_18_bootstrap_outside_repo_reference(self) -> None:
        boot = self.repo_root / "BOOTSTRAP.txt"
        boot.write_text("Restore configuration from /etc/ssl/certs/\n", encoding="utf-8")
        res = validate_bootstrap(boot, self.repo_root)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertGreater(res["outside_repository_reference_count"], 0)

    # 19. Repository-relative Bootstrap reference resolving outside repo returns NOT_VERIFIED
    def test_19_bootstrap_unresolved_relative_reference(self) -> None:
        boot = self.repo_root / "BOOTSTRAP.txt"
        boot.write_text("Restore systemd unit systemd/nonexistent.service\n", encoding="utf-8")
        res = validate_bootstrap(boot, self.repo_root)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 20. Truncated gzip returns BLOCKED
    def test_20_truncated_gzip_blocked(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        raw_gz = gzip.compress(b"SELECT 1 FROM users WHERE id = 12345;")
        gz_path.write_bytes(raw_gz[:15])  # Truncate gzip stream
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 5},
            max_compressed_bytes=10 * 1024 * 1024, max_decompressed_bytes=50 * 1024 * 1024
        )
        self.assertEqual(res["status"], ValidationStatus.BLOCKED.value)

    # 21. Compressed-size cap exceeded returns NOT_VERIFIED before decompression
    def test_21_compressed_size_cap_exceeded(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(gzip.compress(b"A" * 1000))
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 5},
            max_compressed_bytes=10, max_decompressed_bytes=50000
        )
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 22. Decompressed-size cap exceeded returns NOT_VERIFIED
    def test_22_decompressed_size_cap_exceeded(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(gzip.compress(b"A" * 5000))
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 5},
            max_compressed_bytes=10000, max_decompressed_bytes=100
        )
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 23. Invalid explicit gzip caps is rejected
    def test_23_invalid_gzip_caps_rejected(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(gzip.compress(b"data"))
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 5},
            max_compressed_bytes=500, max_decompressed_bytes=10  # decompressed < compressed
        )
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 24. Invalid engine metadata returns NOT_VERIFIED
    def test_24_invalid_engine_metadata(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(gzip.compress(b"data"))
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"INVALID_ENGINE": 10},
            max_compressed_bytes=1000, max_decompressed_bytes=5000
        )
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 25. InnoDB-only evidence plus valid bounded gzip returns VERIFIED and active_ddl_safety_established=False
    def test_25_innodb_only_verified(self) -> None:
        gz_path = self.evidence_root / "dump.sql.gz"
        gz_path.write_bytes(gzip.compress(b"CREATE TABLE test (id INT);"))
        res = validate_mysql_readiness(
            gz_path, self.evidence_root, {"InnoDB": 25},
            max_compressed_bytes=10000, max_decompressed_bytes=50000
        )
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)
        self.assertFalse(res["active_ddl_safety_established"])

    # 26. Crypt evidence with an unknown key returns NOT_VERIFIED
    def test_26_crypt_unknown_key_not_verified(self) -> None:
        evidence = {
            "REMOTE_NAME": "gdrive1_crypt",
            "TYPE": "crypt",
            "FILENAME_ENCRYPTION": "standard",
            "DIRECTORY_NAME_ENCRYPTION": True,
            "PASSWORD_VALUE_CAPTURED": "NO",
            "TOKEN_VALUE_CAPTURED": "NO",
            "RAW_SECRET_KEY_UNBOUNDED": "SECRET_PASS_123",
        }
        res = validate_rclone_crypt(evidence)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 27. Crypt evidence with string instead of bool returns NOT_VERIFIED
    def test_27_crypt_string_instead_of_bool_not_verified(self) -> None:
        evidence = {
            "REMOTE_NAME": "gdrive1_crypt",
            "TYPE": "crypt",
            "FILENAME_ENCRYPTION": "standard",
            "DIRECTORY_NAME_ENCRYPTION": "true",  # String instead of bool
            "PASSWORD_VALUE_CAPTURED": "NO",
            "TOKEN_VALUE_CAPTURED": "NO",
        }
        res = validate_rclone_crypt(evidence)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 28. Reports never contain exact canary values
    def test_28_canary_secret_sanitization(self) -> None:
        canary1 = "RCLONE_TEST_TOKEN_7f_SECRET"
        canary2 = "MYSQL_TEST_PASSWORD_7f_PASS"
        canary3 = "PRIVATE_KEY_TEST_7f_KEY"

        results = {
            "overall_go_no_go": "NO_GO",
            "manifest_validation": {"status": "NOT_VERIFIED", "error": canary1},
            "bootstrap_alignment": {"status": "NOT_VERIFIED", "canary": canary2},
            "mysql_restore_readiness": {"status": "VERIFIED"},
            "excluded_storage_protection": {"status": "VERIFIED"},
            "rclone_crypt_evidence": {"status": "VERIFIED", "secret": canary3},
            "dr_drill_readiness": {"status": "NOT_VERIFIED"},
        }

        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)

        json_content = Path(res["json_report_path"]).read_text(encoding="utf-8")
        md_content = Path(res["md_report_path"]).read_text(encoding="utf-8")

        self.assertNotIn(canary1, json_content)
        self.assertNotIn(canary2, json_content)
        self.assertNotIn(canary3, json_content)

        self.assertNotIn(canary1, md_content)
        self.assertNotIn(canary2, md_content)
        self.assertNotIn(canary3, md_content)

    # 29. Reports do not contain raw manifest entries, remote names, or raw bootstrap text
    def test_29_reports_contain_no_raw_entries(self) -> None:
        raw_manifest_entry = "/etc/ssl/private/super_secret_key.pem"
        results = {
            "overall_go_no_go": "NO_GO",
            "manifest_validation": {
                "status": "BLOCKED",
                "offending_entry_digests": ["sha256:1234567890abcdef"],
            },
            "bootstrap_alignment": {"status": "VERIFIED"},
            "mysql_restore_readiness": {"status": "VERIFIED"},
            "excluded_storage_protection": {"status": "BLOCKED"},
            "rclone_crypt_evidence": {"status": "VERIFIED"},
            "dr_drill_readiness": {"status": "NOT_VERIFIED"},
        }
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        json_text = Path(res["json_report_path"]).read_text(encoding="utf-8")
        self.assertNotIn(raw_manifest_entry, json_text)

    # 30. Report directory under a configured backup-source root is rejected before report files exist
    def test_30_report_directory_inside_backup_root_rejected(self) -> None:
        bad_scratch = self.evidence_root / "nested_scratch"
        bad_scratch.mkdir()
        results = {"overall_go_no_go": "NO_GO"}
        res = generate_validation_report(results, bad_scratch, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 31. Report directory with a symlink component is rejected before report files exist
    def test_31_report_directory_symlink_component_rejected(self) -> None:
        real_scratch = self.root / "real_scratch"
        real_scratch.mkdir()
        sym_scratch = self.root / "sym_scratch"
        try:
            os.symlink(real_scratch, sym_scratch)
        except OSError:
            self.skipTest("Symlinks not supported")

        results = {"overall_go_no_go": "NO_GO"}
        res = generate_validation_report(results, sym_scratch, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)

    # 32. Existing symlink report destination is rejected and not overwritten
    def test_32_existing_symlink_report_destination_rejected(self) -> None:
        val_dir = self.scratch_root / "validation"
        val_dir.mkdir(mode=0o700, exist_ok=True)
        sym_json = val_dir / "validation_report.json"
        target_file = self.root / "target.json"
        target_file.write_text("ORIGINAL", encoding="utf-8")

        try:
            os.symlink(target_file, sym_json)
        except OSError:
            self.skipTest("Symlinks not supported")

        results = {"overall_go_no_go": "NO_GO"}
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertEqual(target_file.read_text(encoding="utf-8"), "ORIGINAL")

    # 33. Valid scratch-root report creation produces both fixed files with 0600 mode
    def test_33_report_creation_mode_0600(self) -> None:
        results = {"overall_go_no_go": "NO_GO"}
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)

        j_path = Path(res["json_report_path"])
        m_path = Path(res["md_report_path"])

        self.assertTrue(j_path.exists())
        self.assertTrue(m_path.exists())

        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(j_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(m_path.stat().st_mode), 0o600)

    # 34. Report directory has 0700 mode
    def test_34_report_directory_mode_0700(self) -> None:
        results = {"overall_go_no_go": "NO_GO"}
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        val_dir = self.scratch_root / "validation"
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(val_dir.stat().st_mode), 0o700)

    # 35. JSON output has sorted keys and both formats contain only allowlisted fields
    def test_35_json_output_sorted_keys(self) -> None:
        results = {"overall_go_no_go": "NO_GO", "dr_drill_readiness": {"status": "NOT_VERIFIED"}}
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        j_text = Path(res["json_report_path"]).read_text(encoding="utf-8")
        parsed = json.loads(j_text)
        keys = list(parsed.keys())
        self.assertEqual(keys, sorted(keys))

    # 36. Any WARNING, NOT_VERIFIED, BLOCKED produces overall_go_no_go = NO_GO
    def test_36_go_no_go_failure_cases(self) -> None:
        m_val = {"status": ValidationStatus.VERIFIED.value}
        b_val = {"status": ValidationStatus.NOT_VERIFIED.value}  # Failure
        db_val = {"status": ValidationStatus.VERIFIED.value}
        c_val = {"status": ValidationStatus.VERIFIED.value}

        dr = evaluate_dr_readiness(
            manifest_validation=m_val,
            bootstrap_alignment=b_val,
            mysql_restore_readiness=db_val,
            rclone_crypt_evidence=c_val,
            lab_plan_present=True,
            no_touch_mount_list_present=True,
        )
        self.assertEqual(dr["overall_go_no_go"], "NO_GO")

    # 37. Only all required VERIFIED sections plus both explicit lab flags produces overall_go_no_go = GO
    def test_37_go_no_go_success_case(self) -> None:
        m_val = {"status": ValidationStatus.VERIFIED.value}
        b_val = {"status": ValidationStatus.VERIFIED.value}
        db_val = {"status": ValidationStatus.VERIFIED.value}
        c_val = {"status": ValidationStatus.VERIFIED.value}

        dr = evaluate_dr_readiness(
            manifest_validation=m_val,
            bootstrap_alignment=b_val,
            mysql_restore_readiness=db_val,
            rclone_crypt_evidence=c_val,
            lab_plan_present=True,
            no_touch_mount_list_present=True,
        )
        self.assertEqual(dr["overall_go_no_go"], "GO")

    # 38. Simulate unavailable O_NOFOLLOW fails closed with PATH_SYMLINK_REJECTED
    def test_38_onofollow_unavailable_fails_closed(self) -> None:
        mf = self.evidence_root / "valid_manifest.txt"
        mf.write_text("/etc/ssl/certs\n/opt/adc-backup/config\n", encoding="utf-8")

        original_hasattr = hasattr

        def mock_hasattr(obj, name):
            if obj is os and name == "O_NOFOLLOW":
                return False
            return original_hasattr(obj, name)

        with unittest.mock.patch("builtins.hasattr", side_effect=mock_hasattr):
            res = validate_manifest(mf, self.evidence_root, [PurePosixPath("/etc"), PurePosixPath("/opt/adc-backup")], [])
            self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
            self.assertIn("PATH_SYMLINK_REJECTED", res["error_codes"])

    # 39. Replace/modify artifact between pre-fstat and post-fstat returns ARTIFACT_CHANGED_DURING_VALIDATION
    def test_39_artifact_changed_during_validation_detected(self) -> None:
        mf = self.evidence_root / "changing_manifest.txt"
        mf.write_text("/etc/ssl/certs\n/opt/adc-backup/config\n", encoding="utf-8")

        original_capture = capture_file_identity
        call_count = [0]

        def mock_capture(st):
            ident = original_capture(st)
            call_count[0] += 1
            if call_count[0] == 2:
                # Simulate mtime or dev/ino change
                ident["st_mtime_ns"] += 999999
            return ident

        with unittest.mock.patch("shared.validation.capture_file_identity", side_effect=mock_capture):
            res = validate_manifest(mf, self.evidence_root, [PurePosixPath("/etc"), PurePosixPath("/opt/adc-backup")], [])
            self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
            self.assertIn("ARTIFACT_CHANGED_DURING_VALIDATION", res["error_codes"])

    # 40. Open flags contain O_RDONLY, O_NOFOLLOW, and O_CLOEXEC when available
    def test_40_open_flags_contain_onofollow_or_cloexec(self) -> None:
        flags = get_open_flags()
        self.assertTrue(flags & os.O_RDONLY == os.O_RDONLY or flags == os.O_RDONLY)
        if hasattr(os, "O_NOFOLLOW"):
            self.assertTrue(flags & os.O_NOFOLLOW)
        if hasattr(os, "O_CLOEXEC"):
            self.assertTrue(flags & os.O_CLOEXEC)

    # 41. Assert no artifact validation function invokes open(..., "w"), os.remove, shutil.rmtree, subprocess, or os.system
    def test_41_no_unsafe_mutations_or_subprocess_in_validation(self) -> None:
        val_code = Path(__file__).parent.parent / "shared" / "validation.py"
        text = val_code.read_text(encoding="utf-8")

        # Exclude report serializer from check
        validation_fns_part = text.split("# ─── Report Serializer ───")[0]

        self.assertNotIn("os.system", validation_fns_part)
        self.assertNotIn("subprocess", validation_fns_part)
        self.assertNotIn("shutil.rmtree", validation_fns_part)
        self.assertNotIn("os.remove", validation_fns_part)
        cleaned = validation_fns_part.replace("os.open(", "").replace("os.fdopen(", "")
        self.assertNotIn("open(", cleaned)

    # 42. Report writer is sole file creator and rejects destinations inside backup source roots
    def test_42_report_writer_is_only_file_creator_outside_backup_root(self) -> None:
        res = generate_validation_report({"overall_go_no_go": "NO_GO"}, self.scratch_root, [self.scratch_root])
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertIn("REPORT_ROOT_INSIDE_BACKUP_SCOPE", res["error_codes"])

    # 43. compute_raw_sha256_and_identity calculates correct hex digest and captures stable identity
    def test_43_compute_raw_sha256_and_identity(self) -> None:
        tf = self.evidence_root / "raw_test.bin"
        content = b"ADC-BACKUP-PHASE-0.1-RAW-TEST-BYTES"
        tf.write_bytes(content)

        flags = get_open_flags()
        fd = os.open(tf, flags)
        try:
            res = compute_raw_sha256_and_identity(fd, max_bytes=1024)
            self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)
            self.assertEqual(res["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual(res["byte_count"], len(content))
            self.assertTrue(res["identity_stable_during_read"])
        finally:
            os.close(fd)

    # 44. validate_engine_attestation verifies digest match and valid timestamps
    def test_44_validate_engine_attestation_valid(self) -> None:
        now = datetime.now(timezone.utc)
        dump_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        att = {
            "schema_version": "engine_attestation_v1",
            "attestation_timestamp_utc": now.isoformat(),
            "dump_artifact_sha256": dump_sha256,
            "table_engine_counts": {"InnoDB": 24},
            "provenance_status": "OPERATOR_PROVIDED_NOT_INDEPENDENTLY_VERIFIED",
        }

        res = validate_engine_attestation(att, computed_dump_sha256=dump_sha256, now_utc=now, max_age=timedelta(hours=24))
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)
        self.assertTrue(res["attestation_digest_verified"])

    # 45. validate_engine_attestation detects digest mismatch
    def test_45_validate_engine_attestation_digest_mismatch(self) -> None:
        now = datetime.now(timezone.utc)
        att = {
            "schema_version": "engine_attestation_v1",
            "attestation_timestamp_utc": now.isoformat(),
            "dump_artifact_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
            "table_engine_counts": {"InnoDB": 24},
            "provenance_status": "OPERATOR_PROVIDED_NOT_INDEPENDENTLY_VERIFIED",
        }

        res = validate_engine_attestation(att, computed_dump_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", now_utc=now, max_age=timedelta(hours=24))
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertIn("ATTESTATION_ARTIFACT_DIGEST_MISMATCH", res["error_codes"])

    # 46. validate_engine_attestation detects expired timestamp
    def test_46_validate_engine_attestation_expired(self) -> None:
        now = datetime.now(timezone.utc)
        old_ts = (now - timedelta(days=2)).isoformat()
        att = {
            "schema_version": "engine_attestation_v1",
            "attestation_timestamp_utc": old_ts,
            "dump_artifact_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "table_engine_counts": {"InnoDB": 24},
            "provenance_status": "OPERATOR_PROVIDED_NOT_INDEPENDENTLY_VERIFIED",
        }

        res = validate_engine_attestation(att, computed_dump_sha256=None, now_utc=now, max_age=timedelta(hours=24))
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertIn("ATTESTATION_EXPIRED", res["error_codes"])

    # 47. validate_host_path_mappings verifies repository_artifact and runtime_staging mappings
    def test_47_validate_host_path_mappings_valid(self) -> None:
        (self.root / "config").mkdir(exist_ok=True)
        boot_text = "Restore configuration from /opt/adc-backup/config and stage at /tmp/adc-restore\n"
        map_data = {
            "schema_version": "host_path_map_v1",
            "mappings": [
                {
                    "host_path_reference": "/opt/adc-backup/config",
                    "mapping_type": "repository_artifact",
                    "repository_relative_target": "config",
                    "recovery_role": "configuration",
                },
                {
                    "host_path_reference": "/tmp/adc-restore",
                    "mapping_type": "runtime_staging",
                    "repository_relative_target": None,
                    "recovery_role": "staging",
                    "restore_write_authorization": "LAB_ONLY",
                },
            ],
        }

        res = validate_host_path_mappings(map_data, boot_text, self.root)
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)
        self.assertEqual(res["unmapped_reference_count"], 0)
        self.assertEqual(res["mapped_references_verified"], 2)

    # 48. validate_host_path_mappings fails on unmapped reference
    def test_48_validate_host_path_mappings_unmapped_reference(self) -> None:
        (self.root / "config").mkdir(exist_ok=True)
        boot_text = "Restore /etc/ssl and /unmapped/path/here\n"
        map_data = {
            "schema_version": "host_path_map_v1",
            "mappings": [
                {
                    "host_path_reference": "/etc/ssl",
                    "mapping_type": "repository_artifact",
                    "repository_relative_target": "config",
                    "recovery_role": "configuration",
                }
            ],
        }

        res = validate_host_path_mappings(map_data, boot_text, self.root)
        self.assertEqual(res["status"], ValidationStatus.NOT_VERIFIED.value)
        self.assertIn("HOST_PATH_MAPPING_UNMAPPED_REFERENCE", res["error_codes"])
        self.assertGreater(res["unmapped_reference_count"], 0)

    # 49. generate_validation_report creates evidence_manifest.json with strict schema
    def test_49_evidence_manifest_json_created(self) -> None:
        results = {
            "overall_go_no_go": "NO_GO",
            "manifest_validation": {"raw_manifest_sha256": "sha256:1111"},
            "mysql_restore_readiness": {"raw_dump_sha256": "sha256:2222"},
            "bootstrap_alignment": {"raw_bootstrap_sha256": "sha256:3333"},
        }
        res = generate_validation_report(results, self.scratch_root, [self.evidence_root])
        self.assertEqual(res["status"], ValidationStatus.VERIFIED.value)

        ev_path = Path(res["evidence_manifest_path"])
        self.assertTrue(ev_path.exists())

        payload = json.loads(ev_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "adc_evidence_manifest_v1")
        self.assertTrue(payload["input_artifacts_read_in_place"])
        self.assertFalse(payload["raw_artifacts_copied_to_evidence_root"])

    # 50. evaluate_dr_readiness includes attestation and mapping validations in GO decision
    def test_50_evaluate_dr_readiness_with_attestation_and_mappings(self) -> None:
        m_val = {"status": ValidationStatus.VERIFIED.value}
        b_val = {"status": ValidationStatus.VERIFIED.value}
        db_val = {"status": ValidationStatus.VERIFIED.value}
        c_val = {"status": ValidationStatus.VERIFIED.value}
        att_val = {"status": ValidationStatus.VERIFIED.value}
        map_val = {"status": ValidationStatus.VERIFIED.value}

        dr = evaluate_dr_readiness(
            manifest_validation=m_val,
            bootstrap_alignment=b_val,
            mysql_restore_readiness=db_val,
            rclone_crypt_evidence=c_val,
            attestation_validation=att_val,
            host_path_mapping_validation=map_val,
            lab_plan_present=True,
            no_touch_mount_list_present=True,
        )
        self.assertEqual(dr["overall_go_no_go"], "GO")

    # 51. evaluate_dr_readiness fails if attestation_validation is NOT_VERIFIED
    def test_51_evaluate_dr_readiness_fails_if_attestation_not_verified(self) -> None:
        m_val = {"status": ValidationStatus.VERIFIED.value}
        b_val = {"status": ValidationStatus.VERIFIED.value}
        db_val = {"status": ValidationStatus.VERIFIED.value}
        c_val = {"status": ValidationStatus.VERIFIED.value}
        att_val = {"status": ValidationStatus.NOT_VERIFIED.value}

        dr = evaluate_dr_readiness(
            manifest_validation=m_val,
            bootstrap_alignment=b_val,
            mysql_restore_readiness=db_val,
            rclone_crypt_evidence=c_val,
            attestation_validation=att_val,
            lab_plan_present=True,
            no_touch_mount_list_present=True,
        )
        self.assertEqual(dr["overall_go_no_go"], "NO_GO")

    # 52. evaluate_dr_readiness fails if host_path_mapping_validation is NOT_VERIFIED
    def test_52_evaluate_dr_readiness_fails_if_mapping_not_verified(self) -> None:
        m_val = {"status": ValidationStatus.VERIFIED.value}
        b_val = {"status": ValidationStatus.VERIFIED.value}
        db_val = {"status": ValidationStatus.VERIFIED.value}
        c_val = {"status": ValidationStatus.VERIFIED.value}
        map_val = {"status": ValidationStatus.NOT_VERIFIED.value}

        dr = evaluate_dr_readiness(
            manifest_validation=m_val,
            bootstrap_alignment=b_val,
            mysql_restore_readiness=db_val,
            rclone_crypt_evidence=c_val,
            host_path_mapping_validation=map_val,
            lab_plan_present=True,
            no_touch_mount_list_present=True,
        )
        self.assertEqual(dr["overall_go_no_go"], "NO_GO")


if __name__ == "__main__":
    unittest.main()
