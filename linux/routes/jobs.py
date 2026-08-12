"""
linux/routes/jobs.py — Backup job management with parallel dual-account support.
"""

from __future__ import annotations

import json
import threading

from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, url_for,
)

from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("jobs", __name__)


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    jobs = db.get_jobs("linux", db_path)
    remotes = db.get_remotes(db_path)
    recent_by_job: dict = {}
    for j in jobs:
        runs = db.get_runs(job_id=j["id"], limit=1, db_path=db_path)
        recent_by_job[j["id"]] = runs[0] if runs else None
    return render_template("jobs.html", jobs=jobs, remotes=remotes, recent_by_job=recent_by_job)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    db_path = current_app.config["DB_PATH"]
    data = request.form
    try:
        mode = data.get("mode", "copy")
        if mode == "sync":
            sync_ok = db.get_state_value("sync_mode_enabled", db_path)
            if sync_ok != "1":
                flash("Sync mode is globally disabled. Enable it in Settings first.", "error")
                return redirect(url_for("jobs.index"))
        target_cnt = int(data.get("target_count", 2))
        jid = db.add_job({
            "name": data["name"].strip(),
            "host": "linux",
            "data_class": data["data_class"],
            "remote_id": int(data["remote_id"]) if data.get("remote_id") else None,
            "mode": mode,
            "target_count": target_cnt,
            "schedule_cron": data.get("schedule_cron", "").strip() or None,
            "extra_flags": data.get("extra_flags", "[]"),
            "pre_hook": data.get("pre_hook", "").strip() or None,
            "notify_on_failure": int(data.get("notify_on_failure", 1)),
            "notify_on_success": int(data.get("notify_on_success", 0)),
            "notes": data.get("notes", "").strip(),
        }, db_path)
        db.audit("admin", "job.create", "job", jid, {"name": data["name"], "target_count": target_cnt}, db_path)
        from linux.scheduler import sync_jobs
        sync_jobs(db_path)
        flash(f"Job '{data['name']}' created ({target_cnt}-way parallel replication).", "success")
    except Exception as exc:
        flash(f"Error creating job: {exc}", "error")
    return redirect(url_for("jobs.index"))


@bp.route("/<int:jid>/toggle", methods=["POST"])
@login_required
def toggle(jid):
    db_path = current_app.config["DB_PATH"]
    new_val = db.toggle_job(jid, db_path)
    db.audit("admin", "job.toggle", "job", jid, {"enabled": new_val}, db_path)
    from linux.scheduler import sync_jobs
    sync_jobs(db_path)
    return jsonify({"enabled": new_val})


@bp.route("/<int:jid>/delete", methods=["POST"])
@login_required
def delete(jid):
    db_path = current_app.config["DB_PATH"]
    job = db.get_job(jid, db_path)
    confirm = request.form.get("confirm_name", "").strip()
    if not job:
        flash("Job not found.", "error")
        return redirect(url_for("jobs.index"))
    if confirm != job["name"]:
        flash("Confirmation name did not match. Job not deleted.", "error")
        return redirect(url_for("jobs.index"))
    db.audit("admin", "job.delete", "job", jid, {"name": job["name"]}, db_path)
    db.delete_job(jid, db_path)
    from linux.scheduler import remove_job
    remove_job(jid)
    flash(f"Job '{job['name']}' deleted.", "success")
    return redirect(url_for("jobs.index"))


@bp.route("/<int:jid>/run", methods=["POST"])
@login_required
def run_now(jid):
    db_path = current_app.config["DB_PATH"]
    from linux.engine import get_running_job
    if get_running_job():
        return jsonify({"error": "Another job is already running"}), 409

    body = request.get_json(silent=True) or request.form
    dry_run = str(body.get("dry_run", "false")).lower() in ("true", "1")
    dual_account = str(body.get("dual_account", "false")).lower() in ("true", "1")

    db.audit("admin", "job.run_now", "job", jid, {"dry_run": dry_run, "dual_account": dual_account}, db_path)

    from linux.engine import run_job
    def _bg():
        try:
            run_job(jid, triggered_by="manual", dry_run=dry_run, dual_account=dual_account, db_path=db_path)
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error("run_now error: %s", exc)

    threading.Thread(target=_bg, daemon=True).start()
    return jsonify({"ok": True, "dry_run": dry_run, "dual_account": dual_account})


@bp.route("/running-status")
@login_required
def running_status():
    from linux.engine import get_running_job
    return jsonify(get_running_job())
