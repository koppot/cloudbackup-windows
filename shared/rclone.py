"""
shared/rclone.py — rclone subprocess wrapper for CloudBackup for Windows.

Responsibilities:
  - Build and execute rclone copy / rclone sync commands as subprocesses.
  - Write immutable per-run log files.
  - Detect rotation trigger conditions (exit code 5, capacity below threshold).
  - Check drive capacity via `rclone about`.
  - Support browser-based OAuth authorization flow.
  - Never store or log passphrases.

All rclone operations are run via subprocess, never via rclone mount.

Exit code semantics (rclone):
  0  = Success
  1  = Syntax or usage error
  2  = Error not otherwise categorised
  3  = Directory not found
  4  = File not found
  5  = Temporary error; retried — also used for quota/drive-full conditions
  6  = Less serious errors (e.g. 1 file failed to transfer)
  7  = Fatal error
  8  = Transfer exceeded — limits crossed
  9  = Operation successful, but no files transferred
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .config import AppConfig, DriveRemoteConfig, RcloneConfig


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
    drive_full: bool = False      # True if exit code or output indicates quota exceeded

    @property
    def success(self) -> bool:
        return self.exit_code == 0

    @property
    def partial(self) -> bool:
        """Non-fatal transfer errors: some files failed but others succeeded."""
        return self.exit_code == 6

    @property
    def status(self) -> str:
        if self.exit_code == 0:
            return "success"
        if self.exit_code == 9:
            return "success"   # No files to transfer = success
        if self.exit_code == 6:
            return "partial"
        if self.drive_full:
            return "full"
        return "failed"

    def command_str(self) -> str:
        return " ".join(self.command)


@dataclass
class CapacityInfo:
    remote: str
    total_gb: float
    used_gb: float
    free_gb: float
    pct_used: float
    raw: dict = field(default_factory=dict)

    @property
    def is_below_threshold(self) -> bool:
        """Evaluated by the rotation engine against configured margins."""
        return False   # Caller compares against config thresholds


# ─────────────────────────────────────────────────────────────────────────────
# Log file management
# ─────────────────────────────────────────────────────────────────────────────

def _make_log_path(log_dir: str, run_id: Optional[int] = None) -> str:
    """
    Return a deterministic, immutable log file path.
    Pattern: <log_dir>/YYYY-MM-DD/run-<id|timestamp>.log
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_dir = Path(log_dir) / today
    day_dir.mkdir(parents=True, exist_ok=True)
    suffix = str(run_id) if run_id is not None else str(int(time.time() * 1000))
    return str(day_dir / f"run-{suffix}.log")


# ─────────────────────────────────────────────────────────────────────────────
# Stats parser — extract rclone stats from log output
# ─────────────────────────────────────────────────────────────────────────────

_STATS_BYTES_RE    = re.compile(r"Transferred:\s+([\d.]+\s+[KMGTP]?iB)", re.I)
_STATS_FILES_RE    = re.compile(r"Transferred:\s+(\d+)\s*/\s*\d+", re.I)
_STATS_ERRORS_RE   = re.compile(r"Errors:\s+(\d+)", re.I)
_STATS_CHECKS_RE   = re.compile(r"Checks:\s+(\d+)", re.I)
_QUOTA_ERR_RE      = re.compile(
    r"(quota exceeded|storage quota|drive storage quota|"
    r"The user's Drive storage quota has been exceeded|"
    r"userRateLimitExceeded|rateLimitExceeded|"
    r"403.*quota)",
    re.I,
)


def _parse_stats(text: str) -> dict:
    """Extract transfer statistics from rclone log output."""
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

    # Count transferred file lines
    stats["files_transferred"] = len(re.findall(r"Copied\s*\(new\)|Copied\s*\(replaced", text))

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Tailscale IP detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_tailscale_ip() -> Optional[str]:
    """
    Return the Tailscale interface IP (100.x.x.x) if available, else None.
    Used by the server to bind to the correct interface.
    """
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
        if ip and ip.startswith("100."):
            return ip
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: inspect network interfaces (if fcntl is available)
    try:
        import socket
        import struct
        import fcntl

        SIOCGIFADDR = 0x8915
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        iface = b"tailscale0"
        result_bytes = fcntl.ioctl(
            s.fileno(), SIOCGIFADDR,
            struct.pack("256s", iface[:15])
        )
        ip = socket.inet_ntoa(result_bytes[20:24])
        if ip.startswith("100."):
            return ip
    except Exception:
        pass

    return None



# ─────────────────────────────────────────────────────────────────────────────
# Main rclone runner
# ─────────────────────────────────────────────────────────────────────────────

class RcloneRunner:
    """
    Executes rclone commands as subprocesses.

    All operations:
      - Run via subprocess (never mount).
      - Write output to an immutable log file.
      - Are non-destructive by default (copy mode).
      - Detect drive-full conditions and set result.drive_full accordingly.
    """

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._rclone_bin = cfg.rclone.bin
        self._rclone_conf = cfg.rclone_conf
        self._log_dir = cfg.server.log_dir
        self._base_flags = cfg.rclone.base_flags()

    def _which_rclone(self) -> str:
        """Resolve the rclone binary path, raising clearly if not found."""
        if os.path.isabs(self._rclone_bin):
            if not os.path.isfile(self._rclone_bin):
                raise FileNotFoundError(
                    f"rclone binary not found at configured path: {self._rclone_bin}"
                )
            return self._rclone_bin
        found = shutil.which(self._rclone_bin)
        if not found:
            raise FileNotFoundError(
                f"rclone binary '{self._rclone_bin}' not found in PATH. "
                "Install rclone from https://rclone.org/install/"
            )
        return found

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
        dry_run: bool = True,   # ALWAYS dry_run=True by default for sync
        log_path: Optional[str] = None,
    ) -> List[str]:
        """
        Build a sync command.

        WARNING: rclone sync DELETES files on the destination that are not
        present in the source. This is a destructive operation.
        dry_run defaults to True. The caller must explicitly pass dry_run=False
        after the user has confirmed the dry-run output in the UI.
        """
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
        """
        Execute a rclone command, stream output to log file and optional callback.
        Returns a structured RcloneResult.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        log_fh = None
        if log_path:
            log_fh = open(log_path, "w", encoding="utf-8")
            log_fh.write(f"# CloudBackup for Windows — rclone log\n")

            log_fh.write(f"# Command: {' '.join(cmd)}\n")
            log_fh.write(f"# Started: {started_at}\n")
            log_fh.write(f"# {'=' * 60}\n\n")
            log_fh.flush()

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            for line in proc.stdout:  # type: ignore[union-attr]
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
            err_line = f"[ERROR] Failed to run rclone: {exc}\n"
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

        # Drive full: exit code 5 OR 8, OR quota error text in output
        drive_full = stats["drive_full"] or exit_code in (5, 8)

        return RcloneResult(
            command=cmd,
            exit_code=exit_code,
            stdout=full_output,
            stderr="",   # merged into stdout via STDOUT redirect
            log_path=log_path,
            started_at=started_at,
            finished_at=finished_at,
            bytes_transferred=stats.get("bytes_transferred", 0),
            files_transferred=stats.get("files_transferred", 0),
            files_checked=stats.get("files_checked", 0),
            errors=stats.get("errors", 0),
            drive_full=drive_full,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

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
        """
        Run rclone copy from source path to dest_remote:dest_subpath.

        Args:
            source:       Local source path (absolute).
            dest_remote:  rclone crypt remote name including colon, e.g. "gdrive1_crypt:".
            dest_subpath: Path within the remote, e.g. "hostname/config/etc".
            run_id:       Optional run ID for log file naming.
            extra_flags:  Additional rclone flags.
            dry_run:      If True, adds --dry-run (no files transferred).
            on_output:    Optional callback receiving each output line in real-time.
        """
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
        dry_run: bool = True,   # Always default True — destructive operation
        on_output: Optional[Callable[[str], None]] = None,
    ) -> RcloneResult:
        """
        Run rclone sync.

        DESTRUCTIVE: Deletes files on destination not present in source.
        dry_run defaults to True. Set dry_run=False only after UI confirmation.
        The UI layer MUST enforce a two-step confirmation before calling this
        with dry_run=False.
        """
        if not dry_run:
            # Extra guard: check settings table sync_mode_enabled at the engine layer.
            # This is a belt-and-suspenders check; the route layer checks it too.
            pass   # Engine-level check added in engine.py

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

    def copy_restore(
        self,
        source_remote: str,
        source_subpath: str,
        dest: str,
        run_id: Optional[int] = None,
        dry_run: bool = True,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> RcloneResult:
        """
        Restore: rclone copy from Drive remote back to local path.
        Always dry_run=True by default.
        """
        source = f"{source_remote.rstrip(':')}/{source_subpath.lstrip('/')}"
        log_path = _make_log_path(self._log_dir, run_id)
        cmd = self._build_copy_command(
            source=source,
            dest=dest,
            dry_run=dry_run,
            log_path=log_path,
        )
        return self._run_command(cmd, log_path, on_output=on_output)

    def check_capacity(self, remote: DriveRemoteConfig) -> Optional[CapacityInfo]:
        """
        Query Drive storage quota via `rclone about`.
        Returns CapacityInfo or None if the query fails (e.g. unauthorized).
        """
        rclone_bin = self._which_rclone()
        cmd = [
            rclone_bin, "about",
            f"{remote.base_remote.rstrip(':')}:",
            "--json",
        ] + self._conf_flags()

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)
            total_bytes = data.get("total", 0)
            used_bytes  = data.get("used", 0)
            free_bytes  = data.get("free", total_bytes - used_bytes)

            total_gb = round(total_bytes / (1024 ** 3), 2) if total_bytes else 0.0
            used_gb  = round(used_bytes  / (1024 ** 3), 2)
            free_gb  = round(free_bytes  / (1024 ** 3), 2)
            pct_used = round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0.0

            return CapacityInfo(
                remote=remote.name,
                total_gb=total_gb,
                used_gb=used_gb,
                free_gb=free_gb,
                pct_used=pct_used,
                raw=data,
            )
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            return None

    def is_rotation_needed(
        self,
        capacity: Optional[CapacityInfo],
        reserve_pct: float,
        reserve_bytes_gb: float,
    ) -> bool:
        """
        Return True if the drive should be rotated based on capacity.
        Called before each backup job runs to catch nearly-full drives early.
        """
        if capacity is None:
            return False   # Unknown capacity: do not preemptively rotate
        reserve_gb = reserve_bytes_gb / (1024 ** 3)
        pct_threshold = 100.0 - reserve_pct
        return (
            capacity.free_gb < reserve_gb
            or capacity.pct_used > pct_threshold
        )

    def authorize_remote(self, remote_name: str) -> bool:
        """
        Launch the browser-based OAuth flow for a Google Drive remote.
        Calls `rclone authorize drive` which opens the system browser.
        This is interactive and must be run in a terminal or triggered via
        the UI with instructions to the user (token is returned to config).

        Returns True if authorization succeeded (based on exit code).
        """
        rclone_bin = self._which_rclone()
        cmd = [rclone_bin, "authorize", "drive"] + self._conf_flags()

        try:
            result = subprocess.run(cmd, timeout=300)
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def list_remotes(self) -> List[str]:
        """List remotes configured in rclone.conf."""
        rclone_bin = self._which_rclone()
        try:
            result = subprocess.run(
                [rclone_bin, "listremotes"] + self._conf_flags(),
                capture_output=True, text=True, timeout=10,
            )
            return [r.strip() for r in result.stdout.splitlines() if r.strip()]
        except (subprocess.TimeoutExpired, OSError):
            return []

    def version(self) -> str:
        """Return rclone version string."""
        try:
            result = subprocess.run(
                [self._which_rclone(), "version"],
                capture_output=True, text=True, timeout=5,
            )
            return result.stdout.splitlines()[0] if result.stdout else "unknown"
        except Exception:
            return "unknown"
