"""
windows/engine.py — rclone engine for Windows host (supermicro.local).

Implements Windows-specific backup execution, pre-hooks, Google Drive OAuth setup wizard,
integrity check (rclone check), dry-run restore tests, and PowerShell Task Scheduler integration.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure shared package is in import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import database as db

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", r"C:\ProgramData\CloudBackup\state.db")
RCLONE_BIN = os.environ.get("RCLONE_BIN", r"C:\ProgramFiles\rclone\rclone.exe")
RCLONE_CONF = os.environ.get("RCLONE_CONF", r"C:\ProgramData\CloudBackup\rclone.conf")
LOG_DIR = os.environ.get("LOG_DIR", r"C:\ProgramData\CloudBackup\logs")
HOST_NAME = os.environ.get("HOST_NAME", "supermicro.local")



class WindowsBackupEngine:
    """Backup engine wrapper for Windows 10 host."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._running_job: dict = {}
        self._lock = threading.Lock()

    def get_running_job(self) -> dict:
        with self._lock:
            return dict(self._running_job)

    def run_job(self, job_id: int, triggered_by: str = "manual", dry_run: bool = False, dual_account: bool = False) -> int:
        from shared.dedup import scan_and_deduplicate, save_catalog_batch
        from concurrent.futures import ThreadPoolExecutor, as_completed

        db.init_db(self.db_path)
        job = db.get_job(job_id, db_path=self.db_path)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        target_count = 2 if dual_account else 1
        remotes = db.get_active_remotes(target_count, db_path=self.db_path)
        if not remotes:
            remotes = db.get_remotes(db_path=self.db_path)
            if not remotes:
                raise RuntimeError("No configured Google Drive remotes")

        sources = db.get_sources(host="supermicro.local", db_path=self.db_path)
        source_paths = [s["path"] for s in sources if s["data_class"] == job["data_class"] and s["enabled"]]

        if job["data_class"] == "packages":
            pkg_manifest = self._run_packages_pre_hook()
            if pkg_manifest:
                source_paths.append(pkg_manifest)

        if not source_paths:
            log.warning("No source paths for job %s", job["name"])
            return -1

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_dir = Path(LOG_DIR) / date_str
        log_dir.mkdir(parents=True, exist_ok=True)

        primary_remote = remotes[0]

        # ── Single Source Deduplication Scan ──
        dedup_result = scan_and_deduplicate(
            source_paths=source_paths,
            host="supermicro.local",
            data_class=job["data_class"],
            remote_id=primary_remote["id"],
            db_path=self.db_path,
        )

        manifest_file = log_dir / f"job-{job_id}-manifest.txt"
        with open(manifest_file, "w", encoding="utf-8") as mf:
            for p in dedup_result["to_upload"]:
                mf.write(f"{p}\n")

        mode_label = "Parallel Dual-Account" if len(remotes) > 1 and dual_account else "Single-Account"
        run_id = db.create_run(
            job_id=job_id,
            remote_id=primary_remote["id"],
            triggered_by=triggered_by,
            rclone_command=f"{mode_label} run across {len(remotes)} remotes (dedup_skipped={len(dedup_result['deduplicated'])} files)",
            log_path=str(log_dir / f"run-{job_id}-parent.log"),
            db_path=self.db_path,
        )

        with self._lock:
            self._running_job = {
                "active": True,
                "job_name": job["name"],
                "run_id": run_id,
                "mode": mode_label,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }

        has_manifest = bool(dedup_result["to_upload"])

        def _worker_copy(r: dict) -> dict:
            log_path = str(log_dir / f"run-{run_id}-remote-{r['id']}.log")
            crypt = r["crypt_remote"].rstrip(":")
            dest = f"{crypt}:{HOST_NAME}/{job['data_class']}"
            cmd = [
                RCLONE_BIN, "copy",
                "--config", RCLONE_CONF,
                "--log-file", log_path, "--log-level", "INFO",
            ]
            if has_manifest:
                cmd.extend(["--files-from", str(manifest_file)])
            if dry_run:
                cmd.append("--dry-run")
            if has_manifest:
                cmd.append("C:\\")
            else:
                cmd.extend(source_paths)
            cmd.append(dest)


            target_id = db.create_run_target(
                run_id=run_id, remote_id=r["id"], target_role="primary",
                rclone_command=shlex.join(cmd), log_path=log_path, db_path=self.db_path,
            )

            log.info("Windows Parallel Worker [remote=%s]: %s", r["name"], shlex.join(cmd))
            proc = subprocess.run(cmd, capture_output=True, text=True)
            status = "success" if proc.returncode == 0 else "failed"

            db.finish_run_target(target_id, status, proc.returncode, 0, 0, 0, 1 if proc.returncode != 0 else 0, self.db_path)
            return {"remote_id": r["id"], "remote_name": r["name"], "status": status, "exit_code": proc.returncode}

        results = []
        with ThreadPoolExecutor(max_workers=len(remotes)) as executor:
            futures = [executor.submit(_worker_copy, r) for r in remotes]
            for f in as_completed(futures):
                try:
                    res = f.result()
                    results.append(res)
                    if res["status"] == "success":
                        save_catalog_batch(dedup_result["scanned_records"], run_id=run_id, db_path=self.db_path)
                except Exception as exc:
                    log.error("Windows worker error: %s", exc)

        with self._lock:
            self._running_job.clear()

        successes = sum(1 for r in results if r["status"] == "success")
        parent_status = "success" if successes == len(results) and len(results) > 0 else ("partial" if successes > 0 else "failed")
        parent_exit = 0 if parent_status == "success" else (7 if parent_status == "partial" else 1)

        db.finish_run(run_id, parent_status, parent_exit, 0, 0, len(dedup_result["scanned_records"]), 0, self.db_path)
        log.info("%s Run %d finished: parent_status=%s (%d/%d succeeded)", mode_label, run_id, parent_status, successes, len(results))
        return run_id

    def _run_packages_pre_hook(self) -> Optional[str]:

        """Runs PowerShell Get-Package to export installed package manifest."""
        manifest_dir = Path(LOG_DIR).parent / "packages"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / "windows-packages.csv"
        try:
            ps_cmd = f"Get-Package | Export-Csv -Path '{manifest_path}' -NoTypeInformation"
            subprocess.run(["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd], capture_output=True, timeout=30)
            if manifest_path.exists():
                return str(manifest_path)
        except Exception as exc:
            log.error("Error generating Windows package manifest: %s", exc)
        return None

    def pause(self) -> None:
        db.set_system_state("PAUSED", db_path=self.db_path)
        try:
            subprocess.run(
                ["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", "Disable-ScheduledTask -TaskName 'ADCBackup-Run' -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            log.error("PowerShell Task Scheduler pause failed: %s", exc)

    def resume(self) -> None:
        db.set_system_state("ACTIVE", db_path=self.db_path)
        try:
            subprocess.run(
                ["powershell.exe", "-ExecutionPolicy", "Bypass", "-Command", "Enable-ScheduledTask -TaskName 'ADCBackup-Run' -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=10,
            )
        except Exception as exc:
            log.error("PowerShell Task Scheduler resume failed: %s", exc)

    def is_paused(self) -> bool:
        return db.get_system_state(db_path=self.db_path) == "PAUSED"

    def run_verify(self) -> dict:
        remote = db.get_active_remote(db_path=self.db_path)
        if not remote:
            return {"ok": False, "output": "No active remote configured"}
        crypt = remote["crypt_remote"].rstrip(":")
        cmd = [RCLONE_BIN, "check", f"{crypt}:{HOST_NAME}", "--config", RCLONE_CONF]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return {"ok": res.returncode == 0, "output": (res.stdout + res.stderr)[-1000:]}
        except Exception as exc:
            return {"ok": False, "output": str(exc)}

    def run_restore_test(self) -> dict:
        remote = db.get_active_remote(db_path=self.db_path)
        if not remote:
            return {"ok": False, "output": "No active remote configured"}
        staging_dir = r"C:\ProgramData\adc-backup\restore_test"
        os.makedirs(staging_dir, exist_ok=True)
        crypt = remote["crypt_remote"].rstrip(":")
        cmd = [RCLONE_BIN, "copy", f"{crypt}:{HOST_NAME}/config", staging_dir, "--dry-run", "--config", RCLONE_CONF]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            return {"ok": res.returncode == 0, "output": (res.stdout + res.stderr)[-1000:]}
        except Exception as exc:
            return {"ok": False, "output": str(exc)}

    def setup_wizard(self) -> dict:
        remotes = db.get_remotes(db_path=self.db_path)
        next_idx = len(remotes) + 1
        name = f"gdrive{next_idx}"

        try:
            proc = subprocess.Popen(
                [RCLONE_BIN, "authorize", "drive", "--config", RCLONE_CONF],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            auth_url = None
            start = datetime.now(timezone.utc).timestamp()
            while datetime.now(timezone.utc).timestamp() - start < 6:
                line = proc.stdout.readline() if proc.stdout else ""
                if "http://127.0.0.1:53682/" in line or "accounts.google.com" in line:
                    match = re.search(r'(https?://[^\s]+)', line)
                    if match:
                        auth_url = match.group(1)
                        break

            if not auth_url:
                auth_url = "http://127.0.0.1:53682/auth"

            t = threading.Thread(
                target=self._background_authorize_listener,
                args=(proc, name),
                daemon=True,
            )
            t.start()

            return {
                "name": name,
                "auth_url": auth_url,
                "message": f"Setup wizard initiated for {name}",
            }
        except Exception as exc:
            log.error("Error launching setup wizard: %s", exc)
            return {"error": str(exc)}

    def _background_authorize_listener(self, proc: subprocess.Popen, name: str):
        try:
            out, _ = proc.communicate(timeout=180)
            match = re.search(r'(\{.*"access_token".*\})', out, re.DOTALL)
            if match:
                token_data = json.loads(match.group(1))
                self._register_new_gdrive(name, token_data)
        except Exception as exc:
            log.error("Background wizard authorization error: %s", exc)

    def _register_new_gdrive(self, name: str, token_data: dict):
        base_remote = f"{name}:"
        crypt_remote = f"{name}_crypt:"
        secrets_crypt_remote = f"{name}_secrets_crypt:"

        conf_path = Path(RCLONE_CONF)
        conf_path.parent.mkdir(parents=True, exist_ok=True)
        stanzas = f"""
[{name}]
type = drive
token = {json.dumps(token_data)}

[{name}_crypt]
type = crypt
remote = {name}:adc-backup-data
filename_encryption = standard
directory_name_encryption = true
password = SuperMicroBackup2026!Secure

[{name}_secrets_crypt]
type = crypt
remote = {name}:adc-backup-secrets
filename_encryption = standard
directory_name_encryption = true
password = SuperMicroBackup2026!Secure
"""
        with open(conf_path, "a", encoding="utf-8") as f:
            f.write(stanzas)

        rid = db.add_remote({
            "name": name,
            "provider": "drive",
            "base_remote": base_remote,
            "crypt_remote": crypt_remote,
            "secrets_crypt_remote": secrets_crypt_remote,
            "priority": len(db.get_remotes(db_path=self.db_path)) + 1,
            "fill_threshold_percent": 95.0,
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
        }, db_path=self.db_path)
        log.info("Registered new Google Drive remote %s (ID %d)", name, rid)

    def reauthorize_remote(self, rid: int) -> dict:
        remote = db.get_remote(rid, db_path=self.db_path)
        if not remote:
            return {"error": "Remote not found"}
        try:
            proc = subprocess.Popen(
                [RCLONE_BIN, "authorize", "drive", "--config", RCLONE_CONF],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            auth_url = None
            start = datetime.now(timezone.utc).timestamp()
            while datetime.now(timezone.utc).timestamp() - start < 6:
                line = proc.stdout.readline() if proc.stdout else ""
                if "http://127.0.0.1:53682/" in line or "accounts.google.com" in line:
                    match = re.search(r'(https?://[^\s]+)', line)
                    if match:
                        auth_url = match.group(1)
                        break

            return {
                "name": remote["name"],
                "auth_url": auth_url or "http://127.0.0.1:53682/auth",
                "message": f"Re-authorization initiated for {remote['name']}",
            }
        except Exception as exc:
            return {"error": str(exc)}

    def test_remote(self, rid: int) -> dict:
        remote = db.get_remote(rid, db_path=self.db_path)
        if not remote:
            return {"ok": False, "message": "Remote not found"}
        base = remote["base_remote"].rstrip(":") + ":"
        try:
            res = subprocess.run([RCLONE_BIN, "lsd", base, "--config", RCLONE_CONF, "--max-depth", "1"], capture_output=True, text=True, timeout=30)
            ok = res.returncode == 0
            db.update_remote(rid, {"status": "ok" if ok else "error"}, db_path=self.db_path)
            return {"ok": ok, "message": "Remote connection verified." if ok else res.stderr[-200:]}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def delete_remote(self, rid: int) -> dict:
        remote = db.get_remote(rid, db_path=self.db_path)
        if not remote:
            return {"ok": False, "message": "Remote not found"}
        name = remote["name"]
        base_name = remote["base_remote"].rstrip(":")

        db.delete_remote(rid, db_path=self.db_path)

        # Clean sections from rclone.conf
        if os.path.exists(RCLONE_CONF):
            try:
                cfg = configparser.ConfigParser()
                cfg.read(RCLONE_CONF)
                for sec in [base_name, f"{base_name}_crypt", f"{base_name}_secrets_crypt", name]:
                    if cfg.has_section(sec):
                        cfg.remove_section(sec)
                with open(RCLONE_CONF, "w", encoding="utf-8") as f:
                    cfg.write(f)
            except Exception as exc:
                log.error("Error updating rclone.conf on drive removal: %s", exc)

        return {
            "ok": True,
            "message": f"Drive '{name}' removed from configuration. Backed-up data remains safe and encrypted on Google Drive and can be restored at any time by re-authorizing.",
            "retained": True,
        }
