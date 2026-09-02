"""
shared/rclone.py — rclone subprocess wrapper with strict fail-closed discovery & environment sanitization.

Responsibilities:
  - Fail-closed rclone discovery: require verified bundled rclone.exe with SHA-256 hash verification against shared/rclone_manifest.json. Missing manifest, missing bundle, or hash mismatch halts execution immediately.
  - External override allowed ONLY via explicit absolute path.
  - Prohibit bare 'rclone' or implicit PATH lookups.
  - Sanitize process environment: clear inherited RCLONE_CONFIG/RCLONE_CONF variables.
  - Execute rclone copy / sync using argument lists without shell=True.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .config import AppConfig, DriveRemoteConfig, RcloneConfig
from .paths import (
    get_config_dir,
    get_default_rclone_conf_path,
    get_log_dir,
    get_resource_path,
    validate_local_path,
)
from .subprocess_utils import redact_cmd_list, redact_secrets, run_safe_subprocess

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RcloneResult:
    """Structured result from a single rclone invocation."""
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str
    log_path: Optional[str]
    started_at: str
    finished_at: str
    bytes_transferred: int = 0
    files_transferred: int = 0
    files_checked: int = 0
    errors: int = 0
    drive_full: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def partial(self) -> bool:
        return self.exit_code == 6

    @property
    def status(self) -> str:
        if self.exit_code == 0 or self.exit_code == 9:
            return "success"
        if self.exit_code == 6:
            return "partial"
        if self.drive_full:
            return "full"
        return "failed"

    def command_str(self) -> str:
        return " ".join(redact_cmd_list(self.command))


@dataclass
class CapacityInfo:
    remote: str
    total_gb: float
    used_gb: float
    free_gb: float
    pct_used: float
    raw: dict = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Fail-Closed rclone Discovery Policy
# ─────────────────────────────────────────────────────────────────────────────

def resolve_rclone_binary(configured_path: Optional[str] = None) -> Tuple[Path, str]:
    """
    Resolve and validate the rclone executable strictly according to trust policy.

    Discovery Policy:
    1. If configured_path is passed and non-empty:
       - Must be an absolute path (os.path.isabs). Otherwise, raise ValueError.
       - Verify existence and execute `rclone version` check.
    2. Default / Empty configured_path:
       - Require bundled rclone binary inside PyInstaller app bundle or repository.
       - Load shared/rclone_manifest.json. Missing or malformed manifest raises ValueError/FileNotFoundError.
       - Check bundled executable existence. Missing binary raises FileNotFoundError.
       - Verify SHA-256 hash against manifest expected_sha256. Mismatch fails closed immediately (raises ValueError).
    3. NEVER fallback to arbitrary PATH lookup or shutil.which("rclone").

    Returns:
        (resolved_path, discovery_mode_label)
    """
    # 1. Check explicit external override path if configured
    if configured_path is not None:
        clean_path = str(configured_path).strip()
        if clean_path:
            if not os.path.isabs(clean_path):
                raise ValueError(
                    f"External rclone override path must be an absolute path. Got: '{configured_path}'. "
                    "PATH-derived lookups and bare 'rclone' references are disabled for security."
                )
            cand_path = Path(clean_path)
            if not cand_path.exists() or not cand_path.is_file():
                raise FileNotFoundError(f"Configured rclone binary path not found or not a file: {clean_path}")

            # Validate by running `rclone version`
            res = run_safe_subprocess([str(cand_path), "version"], timeout=5)
            if not res.success:
                raise ValueError(f"Configured external rclone binary at {clean_path} failed version check: {res.stderr}")

            log.warning("Using administrator-configured external rclone override at %s", cand_path)
            return cand_path, "external_override"

    # 2. Bundled binary resolution & fail-closed hash validation
    manifest_path = get_resource_path("shared/rclone_manifest.json")
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Fail-closed error: rclone manifest missing at {manifest_path}. Execution halted."
        )

    try:
        with open(manifest_path, "r", encoding="utf-8") as mf:
            manifest = json.load(mf)
    except Exception as exc:
        raise ValueError(f"Fail-closed error: Malformed rclone manifest at {manifest_path}: {exc}") from exc

    bundled_rel = manifest.get("bundled_binary_relative_path", "bin/rclone.exe")
    bundled_candidates = [
        get_resource_path(bundled_rel),
        get_resource_path("rclone.exe"),
        get_resource_path("bin/rclone"),
    ]

    resolved_cand: Optional[Path] = None
    for cand in bundled_candidates:
        if cand.exists() and cand.is_file():
            resolved_cand = cand
            break

    if not resolved_cand:
        raise FileNotFoundError(
            f"Fail-closed error: Bundled rclone executable missing ({bundled_rel}). Execution halted."
        )

    expected_hash = manifest.get("expected_sha256")
    if expected_hash:
        hasher = hashlib.sha256()
        with open(resolved_cand, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        computed_hash = hasher.hexdigest()
        if computed_hash.lower() != expected_hash.lower():
            raise ValueError(
                f"Fail-closed security check failed: Bundled rclone executable SHA-256 hash mismatch! "
                f"Computed '{computed_hash}' vs Expected '{expected_hash}'. Execution halted."
            )

    return resolved_cand, "bundled"


# ─────────────────────────────────────────────────────────────────────────────
# Log File Management
# ─────────────────────────────────────────────────────────────────────────────

def _make_log_path(log_dir: str, run_id: Optional[int] = None) -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = Path(log_dir) / today
    day_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(run_id) if run_id is not None else str(int(time.time() * 1000))
    return str(day_dir / f"run-{suffix}.log")


_STATS_ERRORS_RE = re.compile(r"Errors:\s+(\d+)", re.I)
_STATS_CHECKS_RE = re.compile(r"Checks:\s+(\d+)", re.I)
_QUOTA_ERR_RE = re.compile(
    r"(quota exceeded|storage quota|drive storage quota|"
    r"The user's Drive storage quota has been exceeded|"
    r"userRateLimitExceeded|rateLimitExceeded|"
    r"403.*quota)",
    re.I,
)


def _parse_stats(text: str) -> dict:
    stats: dict = {
        "bytes_transferred": 0,
        "files_transferred": 0,
        "files_checked": 0,
        "errors": 0,
        "drive_full": bool(_QUOTA_ERR_RE.search(text)),
    }
    m = _STATS_ERRORS_RE.search(text)
    if m:
        stats["errors"] = int(m.group(1))
    m = _STATS_CHECKS_RE.search(text)
    if m:
        stats["files_checked"] = int(m.group(1))
    stats["files_transferred"] = len(re.findall(r"Copied\s*\(new\)|Copied\s*\(replaced", text))
    return stats


def detect_tailscale_ip() -> Optional[str]:
    try:
        res = run_safe_subprocess(["tailscale", "ip", "-4"], timeout=5)
        ip = res.stdout.strip()
        if ip and ip.startswith("100."):
            return ip
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Main rclone runner
# ─────────────────────────────────────────────────────────────────────────────

class RcloneRunner:

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._rclone_bin_cfg = cfg.rclone.bin
        self._rclone_conf = cfg.rclone_conf or str(get_default_rclone_conf_path())
        self._log_dir = cfg.server.log_dir or str(get_log_dir())
        self._base_flags = cfg.rclone.base_flags()

    def _which_rclone(self) -> str:
        bin_path, mode = resolve_rclone_binary(self._rclone_bin_cfg)
        return str(bin_path)

    def _conf_flags(self) -> List[str]:
        return ["--config", self._rclone_conf]

    def _build_copy_command(
        self,
        source: str,
        dest: str,
        extra_flags: Optional[List[str]] = None,
        dry_run: bool = False,
        log_path: Optional[str] = None,
    ) -> List[str]:
        cmd = [
            self._which_rclone(),
            "copy",
            source,
            dest,
        ]
        cmd += self._conf_flags()
        cmd += self._base_flags
        cmd += ["--log-level", "INFO"]
        if log_path:
            cmd += ["--log-file", log_path]
        if dry_run:
            cmd += ["--dry-run"]
        if extra_flags:
            cmd += extra_flags
        return cmd

    def _build_sync_command(
        self,
        source: str,
        dest: str,
        extra_flags: Optional[List[str]] = None,
        dry_run: bool = True,
        log_path: Optional[str] = None,
    ) -> List[str]:
        cmd = [
            self._which_rclone(),
            "sync",
            source,
            dest,
        ]
        cmd += self._conf_flags()
        cmd += self._base_flags
        cmd += ["--log-level", "INFO"]
        if log_path:
            cmd += ["--log-file", log_path]
        if dry_run:
            cmd += ["--dry-run"]
        if extra_flags:
            cmd += extra_flags
        return cmd

    def _run_command(
        self,
        cmd: List[str],
        log_path: Optional[str],
        on_output: Optional[Callable[[str], None]] = None,
    ) -> RcloneResult:
        started_at = datetime.now(timezone.utc).isoformat()
        stdout_lines: List[str] = []

        log_fh = None
        if log_path:
            log_fh = open(log_path, "w", encoding="utf-8")
            log_fh.write("# CloudBackup for Windows — rclone log\n")
            log_fh.write(f"# Command: {' '.join(redact_cmd_list(cmd))}\n")
            log_fh.write(f"# Started: {started_at}\n")
            log_fh.write(f"# {'=' * 60}\n\n")
            log_fh.flush()

        env = dict(os.environ)
        env.pop("RCLONE_CONFIG", None)
        env.pop("RCLONE_CONF", None)
        env["RCLONE_CONFIG"] = self._rclone_conf

        try:
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=creation_flags,
            )

            for raw_line in proc.stdout:  # type: ignore[union-attr]
                line = redact_secrets(raw_line)
                stdout_lines.append(line)
                if log_fh:
                    log_fh.write(line)
                    log_fh.flush()
                if on_output:
                    on_output(line)

            proc.wait()
            exit_code = proc.returncode

        except Exception as exc:
            exit_code = -1
            err_line = f"[ERROR] Failed to run rclone: {redact_secrets(str(exc))}\n"
            stdout_lines.append(err_line)
            if log_fh:
                log_fh.write(err_line)

        finally:
            if log_fh:
                finished_at_str = datetime.now(timezone.utc).isoformat()
                log_fh.write(f"\n# {'=' * 60}\n")
                log_fh.write(f"# Finished: {finished_at_str}\n")
                log_fh.write(f"# Exit code: {exit_code}\n")
                log_fh.close()

        finished_at = datetime.now(timezone.utc).isoformat()
        full_output = "".join(stdout_lines)
        stats = _parse_stats(full_output)
        drive_full = stats["drive_full"] or exit_code in (5, 8)

        return RcloneResult(
            command=cmd,
            exit_code=exit_code,
            stdout=full_output,
            stderr="",
            log_path=log_path,
            started_at=started_at,
            finished_at=finished_at,
            bytes_transferred=stats.get("bytes_transferred", 0),
            files_transferred=stats.get("files_transferred", 0),
            files_checked=stats.get("files_checked", 0),
            errors=stats.get("errors", 0),
            drive_full=drive_full,
        )

    def copy(
        self,
        source: str,
        dest_remote: str,
        dest_subpath: str,
        run_id: Optional[int] = None,
        extra_flags: Optional[List[str]] = None,
        dry_run: bool = False,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> RcloneResult:
        dest = f"{dest_remote.rstrip(':')}/{dest_subpath.lstrip('/')}"
        log_path = _make_log_path(self._log_dir, run_id)
        cmd = self._build_copy_command(
            source=source,
            dest=dest,
            extra_flags=extra_flags,
            dry_run=dry_run,
            log_path=log_path,
        )
        return self._run_command(cmd, log_path, on_output=on_output)

    def sync(
        self,
        source: str,
        dest_remote: str,
        dest_subpath: str,
        run_id: Optional[int] = None,
        extra_flags: Optional[List[str]] = None,
        dry_run: bool = True,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> RcloneResult:
        dest = f"{dest_remote.rstrip(':')}/{dest_subpath.lstrip('/')}"
        log_path = _make_log_path(self._log_dir, run_id)
        cmd = self._build_sync_command(
            source=source,
            dest=dest,
            extra_flags=extra_flags,
            dry_run=dry_run,
            log_path=log_path,
        )
        return self._run_command(cmd, log_path, on_output=on_output)

    def check_capacity(self, remote: DriveRemoteConfig) -> Optional[CapacityInfo]:
        try:
            rclone_bin = self._which_rclone()
            cmd = [
                rclone_bin, "about",
                f"{remote.base_remote.rstrip(':')}:",
                "--json",
            ] + self._conf_flags()

            res = run_safe_subprocess(cmd, timeout=30)
            if not res.success:
                return None

            data = json.loads(res.stdout)
            total_bytes = data.get("total", 0)
            used_bytes = data.get("used", 0)
            free_bytes = data.get("free", total_bytes - used_bytes)

            total_gb = round(total_bytes / (1024 ** 3), 2) if total_bytes else 0.0
            used_gb = round(used_bytes / (1024 ** 3), 2)
            free_gb = round(free_bytes / (1024 ** 3), 2)
            pct_used = round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0.0

            return CapacityInfo(
                remote=remote.name,
                total_gb=total_gb,
                used_gb=used_gb,
                free_gb=free_gb,
                pct_used=pct_used,
                raw=data,
            )
        except Exception:
            return None

    def is_rotation_needed(
        self,
        capacity: Optional[CapacityInfo],
        reserve_pct: float,
        reserve_bytes_gb: float,
    ) -> bool:
        if capacity is None:
            return False
        reserve_gb = reserve_bytes_gb / (1024 ** 3)
        pct_threshold = 100.0 - reserve_pct
        return (
            capacity.free_gb < reserve_gb
            or capacity.pct_used > pct_threshold
        )

    def version(self) -> str:
        try:
            res = run_safe_subprocess([self._which_rclone(), "version"], timeout=5)
            lines = res.stdout.splitlines()
            return lines[0] if lines else "unknown"
        except Exception:
            return "unknown"
