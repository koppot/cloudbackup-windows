"""
linux/engine.py — rclone subprocess wrapper, job runner, and parallel drive replication engine.
Version 2.0: Parallel multi-drive fan-out & run_targets execution.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/opt/adc-backup/db/state.db")
RCLONE_BIN = os.environ.get("RCLONE_BIN", "/usr/bin/rclone")
RCLONE_CONF = os.environ.get("RCLONE_CONF", "/opt/adc-backup/rclone.conf")
LOG_DIR = os.environ.get("LOG_DIR", "/opt/adc-backup/logs")
HOST_NAME = os.environ.get("HOST_NAME", "linux-control")
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.environ.get("MYSQL_PORT", "3306")
MYSQL_USER = os.environ.get("MYSQL_USER", "backup_user")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DUMP_DIR = os.environ.get("MYSQL_DUMP_DIR", "/opt/adc-backup/dumps")
SECRETS_CLASS_YAML = os.environ.get("SECRETS_CLASS_YAML", "/opt/adc-backup/config/secrets_class.yaml")

_lock = threading.Lock()
_running_job: dict = {}


def get_running_job() -> dict:
    with _lock:
        return dict(_running_job)


def _set_running(run_id: int, job_id: int, job_name: str, pid: int = 0) -> None:
    with _lock:
        _running_job.update({
            "run_id": run_id,
            "job_id": job_id,
            "job_name": job_name,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "last_output": [],
            "pid": pid,
        })


def _append_output(line: str) -> None:
    with _lock:
        if "last_output" in _running_job:
            _running_job["last_output"].append(line)
            if len(_running_job["last_output"]) > 50:
                _running_job["last_output"] = _running_job["last_output"][-50:]


def _clear_running() -> None:
    with _lock:
        _running_job.clear()


# ─── mysqldump pre-hook ────────────────────────────────────────────────────────

def run_mysqldump(dump_dir: str = MYSQL_DUMP_DIR) -> str:
    Path(dump_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_file = Path(dump_dir) / f"all-databases-{ts}.sql.gz"

    cmd = [
        "mysqldump",
        f"--host={MYSQL_HOST}",
        f"--port={MYSQL_PORT}",
        f"--user={MYSQL_USER}",
        f"--password={MYSQL_PASSWORD}",
        "--all-databases",
        "--single-transaction",
        "--quick",
        "--lock-tables=false",
    ]
    log.info("Running mysqldump → %s", dump_file)
    with open(dump_file, "wb") as fh:
        gz = subprocess.Popen(["gzip", "-c"], stdin=subprocess.PIPE, stdout=fh)
        dump = subprocess.run(cmd, stdout=gz.stdin, stderr=subprocess.PIPE, check=True)
        gz.stdin.close()
        gz.wait()
    log.info("mysqldump complete: %s (%d bytes)", dump_file, dump_file.stat().st_size)
    return str(dump_file)


# ─── Package list pre-hook ─────────────────────────────────────────────────────

def run_package_snapshot(dump_dir: str = MYSQL_DUMP_DIR) -> None:
    out_dir = Path(dump_dir).parent / "packages"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(["dpkg", "--get-selections"], capture_output=True, text=True, check=True)
        (out_dir / "packages.list").write_text(result.stdout)
    except Exception as exc:
        log.warning("dpkg snapshot failed: %s", exc)
    try:
        result = subprocess.run(["pip", "freeze"], capture_output=True, text=True)
        (out_dir / "pip-requirements.txt").write_text(result.stdout)
    except Exception as exc:
        log.warning("pip freeze failed: %s", exc)


def get_secrets_paths() -> list[str]:
    import yaml
    yaml_path = Path(SECRETS_CLASS_YAML)
    if not yaml_path.exists():
        return []
    data = yaml.safe_load(yaml_path.read_text())
    return data.get("paths", [])


def resolve_source_paths(job: dict, db_path: str = DB_PATH) -> list[str]:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared.database import get_sources

    if job["data_class"] == "secrets":
        return get_secrets_paths()

    sources = get_sources(host=job.get("host", "linux"), db_path=db_path)
    return [s["path"] for s in sources if s["data_class"] == job["data_class"] and s["enabled"]]


def build_rclone_cmd(
    job: dict,
    remote: dict,
    source_paths: list[str],
    manifest_path: Optional[str],
    run_id: int,
    log_path: str,
    dry_run: bool = False,
    settings: Optional[dict] = None,
) -> list[str]:
    s = settings or {}
    verb = "copy"
    if job.get("mode") == "sync":
        from shared.database import get_state_value
        if get_state_value("sync_mode_enabled") == "1":
            verb = "sync"

    crypt = remote["crypt_remote"].rstrip(":")
    if job["data_class"] == "secrets" and remote.get("secrets_crypt_remote"):
        crypt = remote["secrets_crypt_remote"].rstrip(":")
    dest = f"{crypt}:{HOST_NAME}/{job['data_class']}"

    cmd = [
        RCLONE_BIN, verb,
        "--config", RCLONE_CONF,
        "--tpslimit", s.get("rclone_tpslimit", "10"),
        "--tpslimit-burst", "10",
        "--drive-pacer-min-sleep", "100ms",
        "--drive-pacer-burst", "10",
        "--transfers", s.get("rclone_transfers", "4"),
        "--checkers", s.get("rclone_checkers", "8"),
        "--drive-chunk-size", s.get("rclone_chunk_size", "64M"),
        "--bwlimit", s.get("rclone_bwlimit", "5M"),  # 5 MB/s per worker cap
        "--fast-list",
        "--retries", "5",
        "--low-level-retries", "10",
        "--log-file", log_path,
        "--log-level", s.get("rclone_log_level", "INFO"),
        "--stats", "30s",
        "--stats-log-level", "INFO",
    ]



    if manifest_path:
        cmd.extend(["--files-from", manifest_path])

    if dry_run:
        cmd.append("--dry-run")

    extra = json.loads(job.get("extra_flags", "[]") or "[]")
    cmd.extend(extra)

    if manifest_path:
        cmd.append("/")
    else:
        cmd.extend(source_paths)

    cmd.append(dest)
    return cmd


def check_remote_capacity(remote: dict) -> tuple[bool, float, float]:
    base = remote["base_remote"].rstrip(":") + ":"
    try:
        result = subprocess.run(
            [RCLONE_BIN, "about", base, "--config", RCLONE_CONF, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return True, 0.0, 0.0
        data = json.loads(result.stdout)
        total = data.get("total", 0)
        used = data.get("used", 0)
        total_gb = total / (1024 ** 3)
        used_gb = used / (1024 ** 3)
        threshold = remote.get("fill_threshold_percent", 95.0)
        if total > 0:
            pct = (used / total) * 100
            has_space = pct < threshold and (total_gb - used_gb) >= 10
        else:
            has_space = True
        return has_space, used_gb, total_gb
    except Exception:
        return True, 0.0, 0.0


def _worker_copy_target(
    run_id: int,
    job: dict,
    remote: dict,
    source_paths: list[str],
    manifest_path: Optional[str],
    log_dir: Path,
    dry_run: bool,
    settings: dict,
    db_path: str,
) -> dict:
    """Worker thread that executes an isolated rclone copy stream to a single remote."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared import database as db

    log_path = str(log_dir / f"run-{run_id}-remote-{remote['id']}.log")
    cmd = build_rclone_cmd(job, remote, source_paths, manifest_path, run_id, log_path, dry_run, settings)

    # Ensure destination directory exists on crypt remote
    dest_remote = cmd[-1]
    subprocess.run([RCLONE_BIN, "mkdir", dest_remote, "--config", RCLONE_CONF], capture_output=True, timeout=30)

    target_id = db.create_run_target(
        run_id=run_id, remote_id=remote["id"], target_role="primary",
        rclone_command=shlex.join(cmd), log_path=log_path, db_path=db_path,
    )


    log.info("Parallel Worker [remote=%s]: starting %s", remote["name"], shlex.join(cmd))
    exit_code, bytes_xfr, files_xfr, files_chk, errors = _exec_rclone(cmd, run_id, log_path)

    # Rotation fallback if exit code 5 (drive full)
    if exit_code == 5:
        log.warning("Remote %s full during parallel run; attempting fallback rotation", remote["name"])
        fallback = db.rotate_to_next_remote(remote["id"], db_path)
        if fallback:
            log_path_fb = str(log_dir / f"run-{run_id}-remote-{fallback['id']}-fallback.log")
            cmd_fb = build_rclone_cmd(job, fallback, source_paths, manifest_path, run_id, log_path_fb, dry_run, settings)
            db.create_run_target(run_id=run_id, remote_id=fallback["id"], target_role="fallback",
                                 rclone_command=shlex.join(cmd_fb), log_path=log_path_fb, db_path=db_path)
            exit_code, bytes_xfr, files_xfr, files_chk, errors = _exec_rclone(cmd_fb, run_id, log_path_fb)

    status = "success" if exit_code == 0 else ("partial" if exit_code in (7, 8) else "failed")
    db.finish_run_target(target_id, status, exit_code, bytes_xfr, files_xfr, files_chk, errors, db_path)

    return {
        "target_id": target_id,
        "remote_id": remote["id"],
        "remote_name": remote["name"],
        "status": status,
        "exit_code": exit_code,
        "bytes_xfr": bytes_xfr,
        "files_xfr": files_xfr,
        "errors": errors,
    }


def run_job(
    job_id: int,
    triggered_by: str = "manual",
    dry_run: bool = False,
    dual_account: bool = False,
    db_path: str = DB_PATH,
) -> int:
    """
    Execute a backup job with single-source deduplication and optional parallel dual-account fan-out.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared import database as db
    from shared.dedup import scan_and_deduplicate, save_catalog_batch
    from linux.notifier import notify

    job = db.get_job(job_id, db_path)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    if not job["enabled"] and triggered_by == "scheduler":
        log.info("Job %s is disabled; skipping", job["name"])
        return -1

    settings = db.get_settings(db_path)
    target_count = 2 if dual_account else int(job.get("target_count", 1))

    # ── Remote selection ──
    remotes = db.get_active_remotes(target_count, db_path)
    if not remotes:
        raise RuntimeError("No active Drive remotes available")

    # ── Pre-hooks (run ONCE before fan-out) ──
    if job["data_class"] == "data":
        try:
            run_mysqldump(MYSQL_DUMP_DIR)
        except Exception as exc:
            log.error("mysqldump pre-hook failed: %s", exc)
    elif job["data_class"] == "packages":
        run_package_snapshot(MYSQL_DUMP_DIR)

    # ── Source paths ──
    source_paths = resolve_source_paths(job, db_path)
    if not source_paths:
        log.warning("Job %s has no source paths; skipping", job["name"])
        return -1

    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = Path(LOG_DIR) / date_str
    log_dir.mkdir(parents=True, exist_ok=True)

    # ── Single Source Deduplication Scan (Run ONCE for all targets) ──
    primary_remote_id = remotes[0]["id"]
    dedup_result = scan_and_deduplicate(
        source_paths=source_paths,
        host=job.get("host", "linux"),
        data_class=job["data_class"],
        remote_id=primary_remote_id,
        db_path=db_path,
    )

    # Write manifest file for rclone --files-from
    manifest_file = log_dir / f"job-{job_id}-manifest.txt"
    with open(manifest_file, "w", encoding="utf-8") as mf:
        for p in dedup_result["to_upload"]:
            mf.write(f"{p}\n")

    # Create parent run record
    mode_label = "Parallel Dual-Account" if len(remotes) > 1 and dual_account else "Single-Account"
    run_id = db.create_run(
        job_id=job_id,
        remote_id=primary_remote_id,
        triggered_by=triggered_by,
        rclone_command=f"{mode_label} run across {len(remotes)} remotes (dedup_skipped={len(dedup_result['deduplicated'])} files)",
        log_path=str(log_dir / f"run-{job_id}-parent.log"),
        db_path=db_path,
    )

    _set_running(run_id, job_id, job["name"], pid=0)
    log.info("Starting %s Run %d for job '%s' across remotes %s",
             mode_label, run_id, job["name"], [r["name"] for r in remotes])

    # ── Parallel Fan-Out Execution via ThreadPoolExecutor ──
    manifest_path_str = str(manifest_file) if dedup_result["to_upload"] else None
    results = []

    with ThreadPoolExecutor(max_workers=len(remotes)) as executor:

        futures = [
            executor.submit(_worker_copy_target, run_id, job, r, source_paths,
                            manifest_path_str, log_dir, dry_run, settings, db_path)
            for r in remotes
        ]

        for f in as_completed(futures):
            try:
                res = f.result()
                results.append(res)
                # Save catalog entry for each successfully targeted remote
                if res["status"] in ("success", "partial"):
                    save_catalog_batch(dedup_result["scanned_records"], run_id=run_id, db_path=db_path)
            except Exception as exc:
                log.error("Worker stream error: %s", exc)

    _clear_running()

    # ── Aggregate Status ──
    successes = sum(1 for r in results if r["status"] == "success")
    total_bytes = sum(r["bytes_xfr"] for r in results)
    total_files = sum(r["files_xfr"] for r in results)
    total_errors = sum(r["errors"] for r in results)

    if successes == len(results) and len(results) > 0:
        parent_status = "success"
        parent_exit = 0
    elif successes > 0:
        parent_status = "partial"
        parent_exit = 7
    else:
        parent_status = "failed"
        parent_exit = 1

    db.finish_run(run_id, parent_status, parent_exit, total_bytes, total_files, len(dedup_result["scanned_records"]), total_errors, db_path)

    # ── Notifications ──
    if parent_status in ("failed", "partial") and job.get("notify_on_failure"):
        notify(f"[ADC Backup] Job '{job['name']}' {parent_status.upper()}",
               f"Run {run_id} ({mode_label}) finished with status '{parent_status}'. Targets: {results}",
               settings=settings)
    elif parent_status == "success" and job.get("notify_on_success"):
        notify(f"[ADC Backup] Job '{job['name']}' Succeeded",
               f"Run {run_id} ({mode_label}) successfully replicated across {len(results)} Drive remotes.",
               settings=settings)

    log.info("%s Run %d finished: parent_status=%s (%d/%d succeeded)",
             mode_label, run_id, parent_status, successes, len(results))
    return run_id



def _exec_rclone(cmd: list[str], run_id: int, log_path: str) -> tuple[int, int, int, int, int]:
    bytes_xfr = files_xfr = files_chk = errors = 0
    try:
        with open(log_path, "a", buffering=1) as logf:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
            for line in proc.stdout:
                logf.write(line)
                _append_output(line.rstrip())
                if "Errors:" in line:
                    try:
                        errors = int(line.split("Errors:")[1].strip().split()[0])
                    except Exception:
                        pass
            proc.wait()
        return proc.returncode, bytes_xfr, files_xfr, files_chk, errors
    except Exception as exc:
        log.error("rclone execution error: %s", exc)
        return 1, 0, 0, 0, 1


def run_verify(remote_id: int, data_class: str, db_path: str = DB_PATH) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared import database as db

    remote = db.get_remote(remote_id, db_path)
    if not remote:
        raise ValueError("Remote not found")

    sources = db.get_sources("linux", db_path)
    source_paths = [s["path"] for s in sources if s["data_class"] == data_class and s["enabled"]]
    if not source_paths:
        return {"error": "No source paths found for this class"}

    crypt = remote["crypt_remote"].rstrip(":")
    dest = f"{crypt}:{HOST_NAME}/{data_class}"
    results = []
    for src in source_paths:
        cmd = [RCLONE_BIN, "check", src, dest, "--config", RCLONE_CONF, "--combined", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        results.append({"source": src, "output": result.stdout[-2000:], "exit_code": result.returncode})
    return {"results": results}


def run_restore_test(remote_id: int, data_class: str, staging_dir: str, db_path: str = DB_PATH) -> dict:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared import database as db

    remote = db.get_remote(remote_id, db_path)
    if not remote:
        raise ValueError("Remote not found")

    crypt = remote["crypt_remote"].rstrip(":")
    src = f"{crypt}:{HOST_NAME}/{data_class}"
    cmd = [
        RCLONE_BIN, "copy", src, staging_dir,
        "--config", RCLONE_CONF,
        "--dry-run", "--log-level", "INFO",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return {
        "command": shlex.join(cmd),
        "exit_code": result.returncode,
        "output": (result.stdout + result.stderr)[-3000:],
        "staging_dir": staging_dir,
    }


def execute_restore(restore_id: int, db_path: str = DB_PATH) -> None:
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared import database as db

    restore = db.get_restore(restore_id, db_path)
    if not restore:
        raise ValueError("Restore not found")
    if not restore["confirmed"]:
        raise PermissionError("Restore not confirmed")
    if not restore["dry_run_done"]:
        raise PermissionError("Dry-run must be completed before live restore")

    remote = db.get_remote(restore["remote_id"], db_path)
    crypt = remote["crypt_remote"].rstrip(":")
    src = f"{crypt}:{restore['remote_path']}"
    dest = restore["dest_path"]

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_dir = Path(LOG_DIR) / ts
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = str(log_dir / f"restore-{restore_id}.log")

    cmd = [
        RCLONE_BIN, "copy", src, dest,
        "--config", RCLONE_CONF,
        "--log-file", log_path, "--log-level", "INFO",
    ]

    db.update_restore(restore_id, {"status": "running", "started_at": datetime.now(timezone.utc).isoformat(), "rclone_command": shlex.join(cmd), "log_path": log_path}, db_path)

    def _run():
        result = subprocess.run(cmd, capture_output=True)
        status = "done" if result.returncode == 0 else "failed"
        db.update_restore(restore_id, {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "log_path": log_path,
        }, db_path)
        log.info("Restore %d: %s (exit %d)", restore_id, status, result.returncode)

    threading.Thread(target=_run, daemon=True).start()

