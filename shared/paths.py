"""
shared/paths.py — Centralized Windows path resolution, resource discovery,
directory policy, path safety validation, and single-instance locking for CloudBackup.

Design Rules:
- All filesystem paths use pathlib.Path abstractions.
- Application binaries: C:\\Program Files\\CloudBackup (or runtime installation dir)
- Machine data root: C:\\ProgramData\\CloudBackup
- Machine config: C:\\ProgramData\\CloudBackup\\config
- State & Database: C:\\ProgramData\\CloudBackup\\state
- Logs: C:\\ProgramData\\CloudBackup\\logs
- Temporary staging: C:\\ProgramData\\CloudBackup\\temp
- Per-user preferences (if needed): %LocalAppData%\\CloudBackup
- Frozen PyInstaller resource resolution via sys._MEIPASS
- Single-instance process lock in ProgramData\\CloudBackup\\state\\cloudbackup.lock
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path, PureWindowsPath
from typing import Optional

# Reserved Windows device names
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# Default Machine-Wide Data Root
DEFAULT_PROGRAMDATA_ROOT = Path(r"C:\ProgramData\CloudBackup")


def is_frozen() -> bool:
    """Return True if running inside a PyInstaller frozen executable bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def get_app_dir() -> Path:
    """
    Return the directory where the main application entry point/executable resides.
    In frozen mode: directory containing the executable.
    In source mode: repository root directory.
    """
    if is_frozen():
        return Path(sys.executable).parent.resolve()
    # Assume file is in shared/paths.py -> parent of shared is repo root
    return Path(__file__).parent.parent.resolve()


def get_resource_path(relative_path: str) -> Path:
    """
    Resolve a bundled resource path safely.
    Works in source mode, PyInstaller frozen mode (sys._MEIPASS), and installed mode.
    """
    clean_rel = str(relative_path).lstrip("/\\")
    if is_frozen():
        meipass = Path(getattr(sys, "_MEIPASS")).resolve()
        candidate = meipass / clean_rel
        if candidate.exists():
            return candidate
    # Fallback to app directory / repo root
    app_dir = get_app_dir()
    return (app_dir / clean_rel).resolve()


def get_programdata_dir() -> Path:
    """
    Return the machine-wide application data directory root.
    Uses %ProgramData% environment variable on Windows with fallback to C:\\ProgramData\\CloudBackup.
    """
    env_pd = os.environ.get("ProgramData")
    if env_pd:
        return Path(env_pd) / "CloudBackup"
    return DEFAULT_PROGRAMDATA_ROOT


def get_config_dir() -> Path:
    """Return protected configuration directory: ProgramData\\CloudBackup\\config."""
    return get_programdata_dir() / "config"


def get_state_dir() -> Path:
    """Return database and job state directory: ProgramData\\CloudBackup\\state."""
    return get_programdata_dir() / "state"


def get_log_dir() -> Path:
    """Return log directory: ProgramData\\CloudBackup\\logs."""
    return get_programdata_dir() / "logs"


def get_temp_dir() -> Path:
    """Return managed application staging/temp directory: ProgramData\\CloudBackup\\temp."""
    return get_programdata_dir() / "temp"


def get_localappdata_dir() -> Path:
    """Return per-user preferences directory: %LocalAppData%\\CloudBackup."""
    env_lad = os.environ.get("LOCALAPPDATA")
    if env_lad:
        return Path(env_lad) / "CloudBackup"
    return Path.home() / "AppData" / "Local" / "CloudBackup"


def get_default_db_path() -> Path:
    """Return default SQLite database path."""
    env_db = os.environ.get("DB_PATH")
    if env_db:
        return Path(env_db).resolve()
    return get_state_dir() / "state.db"


def get_default_rclone_conf_path() -> Path:
    """Return default rclone.conf path."""
    env_conf = os.environ.get("RCLONE_CONF")
    if env_conf:
        return Path(env_conf).resolve()
    return get_config_dir() / "rclone.conf"


def ensure_app_directories() -> None:
    """Ensure all required application data directories exist with proper isolation."""
    for d in [get_programdata_dir(), get_config_dir(), get_state_dir(), get_log_dir(), get_temp_dir()]:
        d.mkdir(parents=True, exist_ok=True)


def validate_local_path(
    path_str: str,
    *,
    must_exist: bool = False,
    allow_unc: bool = True,
    allowed_base: Optional[Path] = None,
) -> Path:
    """
    Validate and normalize a local Windows filesystem path safely.

    Validation Rules:
    1. Reject NUL bytes and empty strings.
    2. Convert to pathlib.Path.
    3. Reject Windows reserved names (CON, PRN, NUL, etc.) as filename/stem components.
    4. Validate UNC paths: allow only valid format (\\\\server\\share\\...) if allow_unc is True.
    5. Resolve/canonicalize the path. Handle '..' normalization safely.
    6. If allowed_base is provided, verify the normalized path does not escape allowed_base.
    7. If must_exist is True, verify path exists.

    Note: This function applies ONLY to local filesystem paths (sources, dests, configs).
    Do NOT pass rclone remote specifiers (e.g. "gdrive1_crypt:") to this function.
    """
    if not path_str or not isinstance(path_str, str):
        raise ValueError("Path must be a non-empty string.")

    if "\x00" in path_str:
        raise ValueError("Path contains invalid NUL byte.")

    # Check reserved names in any component
    pure = PureWindowsPath(path_str)
    for part in pure.parts:
        stem = part.split(".")[0].upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise ValueError(f"Path component '{part}' uses Windows reserved device name '{stem}'.")

    # UNC path check
    is_unc = path_str.startswith("\\\\") or path_str.startswith("//")
    if is_unc:
        if not allow_unc:
            raise ValueError("UNC network paths are not permitted for this operation.")
        # Must have \\server\share at minimum
        parts = [p for p in path_str.replace("/", "\\").split("\\") if p]
        if len(parts) < 2:
            raise ValueError(f"Malformed UNC path '{path_str}'. Must specify \\\\server\\share.")

    try:
        candidate = Path(path_str)
        # Resolve without requiring existence when must_exist is False
        if must_exist:
            resolved = candidate.resolve(strict=True)
        else:
            # If path doesn't exist, resolve parent and append name
            if candidate.exists():
                resolved = candidate.resolve()
            else:
                resolved = candidate.parent.resolve() / candidate.name
    except Exception as exc:
        raise ValueError(f"Cannot resolve or normalize path '{path_str}': {exc}") from exc

    if must_exist and not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")

    if allowed_base is not None:
        base_resolved = Path(allowed_base).resolve()
        try:
            resolved.relative_to(base_resolved)
        except ValueError:
            raise ValueError(f"Path '{resolved}' escapes allowed base directory '{base_resolved}'.")

    return resolved


class SingleInstanceLock:
    """
    Process-wide single-instance lock placed in ProgramData\\CloudBackup\\state\\cloudbackup.lock.
    Prevents concurrent engine/server instances from mutating state simultaneously.
    """

    def __init__(self, lock_file: Optional[Path] = None):
        self.lock_file = lock_file or (get_state_dir() / "cloudbackup.lock")
        self._fp = None

    def acquire(self) -> bool:
        """Acquire single-instance lock. Return True if acquired, False if already locked."""
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self._fp = open(self.lock_file, "a+", encoding="utf-8")
            if sys.platform == "win32":
                import msvcrt
                try:
                    msvcrt.locking(self._fp.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    return False
            else:
                import fcntl
                try:
                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return False
            self._fp.seek(0)
            self._fp.truncate()
            self._fp.write(f"pid={os.getpid()}\n")
            self._fp.flush()
            return True
        except Exception:
            return False

    def release(self) -> None:
        """Release the single-instance lock."""
        if self._fp:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        msvcrt.locking(self._fp.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    try:
                        fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                self._fp.close()
            except Exception:
                pass
            finally:
                self._fp = None
                if self.lock_file.exists():
                    try:
                        self.lock_file.unlink()
                    except Exception:
                        pass
