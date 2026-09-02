"""
shared/subprocess_utils.py — Windows-safe subprocess execution helper with credential redaction.

Rules & Security Enforcement:
- Requires argument lists only (`List[str]`). Prohibits `shell=True`.
- Redacts passphrases, OAuth tokens, access tokens, client secrets, and sensitive rclone CLI flags.
- Configurable timeout, working directory, and environment overrides.
- Structured execution output (`SafeSubprocessResult`).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import List, Mapping, Optional

log = logging.getLogger(__name__)

# Patterns for secret redaction in logs and errors
SECRET_PATTERNS = [
    (re.compile(r'("(?:access_token|refresh_token|token|password|client_secret)"\s*:\s*)"[^"]+"', re.I), r'\1"[REDACTED]"'),
    (re.compile(r'--(?:password|token|obscure|pass)\s+([^\s]+)', re.I), r'--password [REDACTED]'),
    (re.compile(r'ya29\.[A-Za-z0-9_-]+'), '[REDACTED_OAUTH_TOKEN]'),
    (re.compile(r'1//[A-Za-z0-9_-]+'), '[REDACTED_REFRESH_TOKEN]'),
    (re.compile(r'Bearer\s+[A-Za-z0-9_.-]+', re.I), 'Bearer [REDACTED_TOKEN]'),
]


def redact_secrets(text: str) -> str:
    """Redact sensitive passwords, bearer tokens, and OAuth secrets from output strings."""
    if not text:
        return ""
    result = text
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_cmd_list(cmd: List[str]) -> List[str]:
    """Redact secret-bearing values from a subprocess command list for safe logging."""
    redacted: List[str] = []
    skip_next = False
    for i, arg in enumerate(cmd):
        if skip_next:
            redacted.append("[REDACTED]")
            skip_next = False
            continue

        if arg in ("--password", "--obscure", "--pass", "--token"):
            redacted.append(arg)
            skip_next = True
        elif "=" in arg and any(arg.lower().startswith(prefix) for prefix in ("--password=", "--pass=", "--token=")):
            param_name = arg.split("=", 1)[0]
            redacted.append(f"{param_name}=[REDACTED]")
        else:
            redacted.append(redact_secrets(arg))
    return redacted


@dataclass
class SafeSubprocessResult:
    """Structured result of a safe subprocess execution."""
    cmd: List[str]
    redacted_cmd: str
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_safe_subprocess(
    cmd: List[str],
    *,
    timeout: Optional[float] = None,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    capture_output: bool = True,
    text: bool = True,
) -> SafeSubprocessResult:
    """
    Execute a process safely using argument arrays without shell=True.

    Args:
        cmd: List of string arguments (cmd[0] is executable path).
        timeout: Maximum execution duration in seconds.
        cwd: Working directory path.
        env: Environment variables dict.
        capture_output: Whether to capture stdout and stderr.
        text: Return decoded string output.

    Returns:
        SafeSubprocessResult containing exit code, redacted logs, and output streams.
    """
    if not isinstance(cmd, (list, tuple)) or not cmd:
        raise ValueError("Subprocess cmd must be a non-empty list of string arguments.")

    for idx, arg in enumerate(cmd):
        if not isinstance(arg, str):
            raise TypeError(f"Command argument at index {idx} must be a string, got {type(arg).__name__}.")

    redacted_list = redact_cmd_list(cmd)
    redacted_cmd_str = " ".join(redacted_list)

    log.debug("Executing safe subprocess: %s", redacted_cmd_str)

    # Windows creation flags for clean process execution without popping cmd windows
    creation_flags = 0
    if os.name == "nt":
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    # Sanitize environment: remove inherited rclone config overrides unless explicitly provided
    proc_env = dict(env) if env is not None else dict(os.environ)
    if env is None:
        proc_env.pop("RCLONE_CONFIG", None)
        proc_env.pop("RCLONE_CONF", None)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=capture_output,
            text=text,
            timeout=timeout,
            cwd=cwd,
            env=proc_env,
            creationflags=creation_flags,
        )
        return SafeSubprocessResult(
            cmd=list(cmd),
            redacted_cmd=redacted_cmd_str,
            exit_code=proc.returncode,
            stdout=redact_secrets(proc.stdout) if proc.stdout else "",
            stderr=redact_secrets(proc.stderr) if proc.stderr else "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        log.error("Subprocess timed out after %s seconds: %s", timeout, redacted_cmd_str)
        return SafeSubprocessResult(
            cmd=list(cmd),
            redacted_cmd=redacted_cmd_str,
            exit_code=-1,
            stdout=redact_secrets(exc.stdout) if isinstance(exc.stdout, str) else "",
            stderr=redact_secrets(exc.stderr) if isinstance(exc.stderr, str) else f"Command timed out after {timeout} seconds",
            timed_out=True,
        )
    except Exception as exc:
        err_msg = redact_secrets(str(exc))
        log.error("Failed to execute subprocess '%s': %s", redacted_cmd_str, err_msg)
        return SafeSubprocessResult(
            cmd=list(cmd),
            redacted_cmd=redacted_cmd_str,
            exit_code=-1,
            stdout="",
            stderr=f"Execution error: {err_msg}",
            timed_out=False,
        )
