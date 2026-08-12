"""
linux/routes/restore.py — Guided restore workflow with successful-target filtering.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, url_for,
)

from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("restore", __name__)

RCLONE_BIN = os.environ.get("RCLONE_BIN", "/usr/bin/rclone")
RCLONE_CONF = os.environ.get("RCLONE_CONF", "/opt/adc-backup/rclone.conf")
HOST_NAME = os.environ.get("HOST_NAME", "linux-control")


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    remotes = db.get_remotes(db_path)
    runs = db.get_runs(limit=50, db_path=db_path)
    # Filter runs to those having at least one successful target stream
    valid_runs = [r for r in runs if r["status"] in ("success", "partial")]
    restores = db.get_restores(limit=20, db_path=db_path)
    return render_template("restore.html", remotes=remotes, runs=valid_runs, restores=restores)


@bp.route("/targets/<int:run_id>")
@login_required
def get_run_targets_api(run_id: int):
    """Return ONLY target remotes that achieved status = 'success' for this run."""
    db_path = current_app.config["DB_PATH"]
    targets = db.get_successful_restore_targets(run_id, db_path)
    return jsonify(targets)


@bp.route("/new", methods=["POST"])
@login_required
def new_restore():
    """Create a restore request (pending state, dry-run not yet done)."""
    db_path = current_app.config["DB_PATH"]
    source_run_id = request.form.get("source_run_id", type=int)
    remote_id = request.form.get("remote_id", type=int)
    data_class = request.form.get("data_class", "")
    dest_path = request.form.get("dest_path", "").strip()
    dest_is_prod = request.form.get("dest_is_production", "0") == "1"

    if not dest_path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest_path = f"/tmp/adc-restore-{data_class}-{ts}"

    if not remote_id:
        flash("Select a valid successful drive remote source.", "error")
        return redirect(url_for("restore.index"))

    # Verify selected remote achieved status='success' if tied to a run
    if source_run_id:
        valid_targets = db.get_successful_restore_targets(source_run_id, db_path)
        valid_remote_ids = {t["remote_id"] for t in valid_targets}
        if remote_id not in valid_remote_ids:
            flash("Selected remote did not complete successfully for this run. Cannot use as restore source.", "error")
            return redirect(url_for("restore.index"))

    rid = db.create_restore({
        "source_run_id": source_run_id,
        "remote_id": remote_id,
        "data_class": data_class,
        "remote_path": f"{HOST_NAME}/{data_class}",
        "dest_path": dest_path,
        "dest_is_production": int(dest_is_prod),
        "operator": "admin",
    }, db_path)
    db.audit("admin", "restore.create", "restore", rid,
             {"data_class": data_class, "dest_path": dest_path, "remote_id": remote_id}, db_path)
    return redirect(url_for("restore.detail", restore_id=rid))


@bp.route("/<int:restore_id>")
@login_required
def detail(restore_id):
    db_path = current_app.config["DB_PATH"]
    restore = db.get_restore(restore_id, db_path)
    if not restore:
        flash("Restore not found.", "error")
        return redirect(url_for("restore.index"))
    log_tail = []
    if restore.get("log_path") and Path(restore["log_path"]).exists():
        with open(restore["log_path"]) as f:
            log_tail = f.readlines()[-100:]
    return render_template("restore_detail.html", restore=restore, log_tail=log_tail)


@bp.route("/<int:restore_id>/dry-run", methods=["POST"])
@login_required
def dry_run(restore_id):
    db_path = current_app.config["DB_PATH"]
    restore = db.get_restore(restore_id, db_path)
    if not restore:
        return jsonify({"error": "not found"}), 404

    remote = db.get_remote(restore["remote_id"], db_path)
    crypt = remote["crypt_remote"].rstrip(":")
    src = f"{crypt}:{restore['remote_path']}"
    dest = restore["dest_path"]

    cmd = [
        RCLONE_BIN, "copy", src, dest,
        "--config", RCLONE_CONF,
        "--dry-run", "--log-level", "INFO",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        db.update_restore(restore_id, {"dry_run_done": 1, "status": "dry_run"}, db_path)
        return jsonify({
            "ok": result.returncode == 0,
            "command": shlex.join(cmd),
            "output": (result.stdout + result.stderr)[-3000:],
        })
    except Exception as exc:
        return jsonify({"ok": False, "output": str(exc)}), 500


@bp.route("/<int:restore_id>/confirm", methods=["POST"])
@login_required
def confirm(restore_id):
    db_path = current_app.config["DB_PATH"]
    restore = db.get_restore(restore_id, db_path)
    if not restore:
        flash("Restore not found.", "error")
        return redirect(url_for("restore.index"))
    if not restore["dry_run_done"]:
        flash("Complete the dry-run preview first.", "error")
        return redirect(url_for("restore.detail", restore_id=restore_id))
    confirm_token = request.form.get("confirm_token", "").strip()
    if confirm_token != restore["data_class"].upper():
        flash(f"Confirmation token incorrect. Type '{restore['data_class'].upper()}' to confirm.", "error")
        return redirect(url_for("restore.detail", restore_id=restore_id))
    db.update_restore(restore_id, {"confirmed": 1}, db_path)
    db.audit("admin", "restore.confirm", "restore", restore_id,
             {"dest_path": restore["dest_path"]}, db_path)
    from linux.engine import execute_restore
    threading.Thread(target=execute_restore, args=(restore_id, db_path), daemon=True).start()
    flash("Restore started. Monitor progress below.", "success")
    return redirect(url_for("restore.detail", restore_id=restore_id))


@bp.route("/verify", methods=["POST"])
@login_required
def verify():
    db_path = current_app.config["DB_PATH"]
    remote_id = request.form.get("remote_id", type=int)
    data_class = request.form.get("data_class", "config")
    from linux.engine import run_verify
    result = run_verify(remote_id, data_class, db_path)
    return jsonify(result)


@bp.route("/test", methods=["POST"])
@login_required
def restore_test():
    db_path = current_app.config["DB_PATH"]
    remote_id = request.form.get("remote_id", type=int)
    data_class = request.form.get("data_class", "config")
    staging = db.get_setting("staging_dir", "/tmp/adc-restore", db_path)
    from linux.engine import run_restore_test
    result = run_restore_test(remote_id, data_class, staging, db_path)
    return jsonify(result)


@bp.route("/bootstrap")
@login_required
def bootstrap():
    return render_template("restore_bootstrap.html")
