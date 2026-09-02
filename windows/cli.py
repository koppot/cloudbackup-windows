"""
windows/cli.py — Primary CLI entry point and server initializer for CloudBackup on Windows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure root directory is in sys.path
root_dir = Path(__file__).parent.parent.resolve()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from shared import database as db
from shared.paths import (
    SingleInstanceLock,
    ensure_app_directories,
    get_default_db_path,
    get_log_dir,
    is_frozen,
)
from windows.engine import WindowsBackupEngine
from windows.web_server import run_windows_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("cloudbackup")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="CloudBackup",
        description="CloudBackup for Windows — Nontechnical Encrypted Multi-Cloud Backup Solution",
    )
    parser.add_argument("--server", action="store_true", default=True, help="Run the local web UI server (default)")
    parser.add_argument("--port", type=int, default=8765, help="Web UI server port (default: 8765)")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Web UI bind address (default: 127.0.0.1)")
    parser.add_argument("--verify", action="store_true", help="Run cloud backup verification check and exit")
    parser.add_argument("--version", action="store_true", help="Show application version and exit")

    args = parser.parse_args()

    if args.version:
        print("CloudBackup for Windows v1.0.0 (x64)")
        return 0

    ensure_app_directories()
    db_path = str(get_default_db_path())
    db.init_db(db_path)

    if args.verify:
        engine = WindowsBackupEngine(db_path=db_path)
        result = engine.run_verify()
        print(f"Verification Result: {'SUCCESS' if result.get('ok') else 'FAILED'}")
        print(result.get("output", ""))
        return 0 if result.get("ok") else 1

    # Single instance lock for server execution
    lock = SingleInstanceLock()
    if not lock.acquire():
        print("Another instance of CloudBackup is already running.")
        return 1

    try:
        log.info("Launching CloudBackup Windows Server on http://%s:%d", args.host, args.port)
        run_windows_server(host=args.host, port=args.port)
        return 0
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
