#!/usr/bin/env python3
"""
Collect Environment Evidence for Phase 1 VM Acceptance Testing.

Gathers OS details, user privilege status, directory paths, ACLs, port listeners,
scheduled task state, and application logs without exposing sensitive credentials.
"""

import os
import sys
import platform
import subprocess
import json
import argparse
import shutil
from pathlib import Path

def get_cmd_output(cmd, check=False) -> str:
    """Run shell command safely and return output string."""
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return res.stdout.strip()
    except Exception as e:
        return f"Error executing command {cmd}: {e}"

def check_binary_on_path(binary_name: str) -> dict:
    """Check if binary is available on system PATH."""
    path = shutil.which(binary_name)
    return {
        "binary": binary_name,
        "on_path": path is not None,
        "resolved_path": path if path else "NONE"
    }

def collect_evidence() -> dict:
    """Collect non-sensitive environment and application evidence."""
    is_windows = sys.platform == "win32"

    evidence = {
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "python_version": sys.version.split()[0]
        },
        "user_identity": {
            "username": os.getlogin() if hasattr(os, "getlogin") else os.getenv("USER") or os.getenv("USERNAME"),
            "is_admin": False
        },
        "path_binary_checks": {
            "python": check_binary_on_path("python") or check_binary_on_path("python3"),
            "git": check_binary_on_path("git"),
            "pip": check_binary_on_path("pip") or check_binary_on_path("pip3"),
            "rclone": check_binary_on_path("rclone")
        },
        "installation_directories": {},
        "listeners_8765": [],
        "task_scheduler": {},
        "acls": {}
    }

    # Admin check
    if is_windows:
        try:
            import ctypes
            evidence["user_identity"]["is_admin"] = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            evidence["user_identity"]["is_admin"] = False
    else:
        evidence["user_identity"]["is_admin"] = (os.geteuid() == 0) if hasattr(os, "geteuid") else False

    # Directory existence checks
    program_files_cb = Path(r"C:\Program Files\CloudBackup") if is_windows else Path("/tmp/ProgramFiles/CloudBackup")
    program_data_cb = Path(r"C:\ProgramData\CloudBackup") if is_windows else Path("/tmp/ProgramData/CloudBackup")

    evidence["installation_directories"]["program_files_exists"] = program_files_cb.exists()
    evidence["installation_directories"]["program_data_exists"] = program_data_cb.exists()

    if program_data_cb.exists():
        subdirs = ["config", "state", "logs", "temp"]
        evidence["installation_directories"]["program_data_subdirs"] = {
            sd: (program_data_cb / sd).exists() for sd in subdirs
        }

    # Port 8765 listener check
    if is_windows:
        netstat_out = get_cmd_output(["netstat", "-ano"])
        for line in netstat_out.splitlines():
            if ":8765" in line:
                evidence["listeners_8765"].append(line)
    else:
        lsof_out = get_cmd_output(["lsof", "-i", ":8765"])
        if lsof_out and "Error" not in lsof_out:
            evidence["listeners_8765"] = lsof_out.splitlines()

    # Task scheduler check
    if is_windows:
        sch_out = get_cmd_output(["schtasks", "/query", "/tn", "CloudBackupTask", "/fo", "LIST"])
        evidence["task_scheduler"]["task_registered"] = "ERROR:" not in sch_out and "CloudBackupTask" in sch_out
        evidence["task_scheduler"]["details"] = sch_out if evidence["task_scheduler"]["task_registered"] else "Not registered"

    # ACL checks via icacls on Windows
    if is_windows:
        if program_files_cb.exists():
            evidence["acls"]["program_files"] = get_cmd_output(["icacls", str(program_files_cb)])
        if program_data_cb.exists():
            evidence["acls"]["program_data"] = get_cmd_output(["icacls", str(program_data_cb)])

    return evidence

def main():
    parser = argparse.ArgumentParser(description="Collect VM environment evidence.")
    parser.add_argument("--output", required=True, help="Path to save evidence JSON artifact.")
    args = parser.parse_args()

    output_path = Path(args.output)
    print(f"Collecting environment evidence...")

    evidence = collect_evidence()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)

    print(f"[OK] Evidence collected and saved to: {output_path}")

if __name__ == "__main__":
    main()
