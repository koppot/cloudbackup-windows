"""
linux/routes/settings.py — Settings, pause/resume, log viewer, user management, and password change.
"""

import os
from pathlib import Path

import bcrypt
from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)
from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("settings", __name__)

LOG_DIR = os.environ.get("LOG_DIR", "/opt/adc-backup/logs")


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    settings = db.get_settings(db_path)
    system_state = db.get_system_state(db_path)
    users = db.get_users(db_path)
    current_username = session.get("username", "admin")
    return render_template("settings.html", settings=settings, system_state=system_state, users=users, current_username=current_username)


@bp.route("/update", methods=["POST"])
@login_required
def update():
    db_path = current_app.config["DB_PATH"]
    allowed_keys = {
        "notify_webhook_url", "notify_email_smtp_host", "notify_email_smtp_port",
        "notify_email_smtp_user", "notify_email_smtp_pass", "notify_email_from",
        "notify_email_to", "rclone_tpslimit", "rclone_transfers", "rclone_checkers",
        "rclone_chunk_size", "rclone_log_level", "log_retention_days", "staging_dir",
    }
    updates = {k: request.form[k] for k in request.form if k in allowed_keys}
    db.update_settings(updates, db_path)
    db.audit(session.get("username", "admin"), "settings.update", detail=list(updates.keys()), db_path=db_path)
    flash("Settings saved.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    db_path = current_app.config["DB_PATH"]
    current_pw = request.form.get("current_password", "")
    new_pw = request.form.get("new_password", "")
    confirm_pw = request.form.get("confirm_password", "")
    user_id = session.get("user_id")
    username = session.get("username", "admin")

    if new_pw != confirm_pw:
        flash("New passwords do not match.", "error")
        return redirect(url_for("settings.index"))

    if len(new_pw) < 8:
        flash("Password must be at least 8 characters long.", "error")
        return redirect(url_for("settings.index"))

    # Verify current password
    user = db.get_user_by_id(user_id, db_path) if user_id else db.get_user_by_username(username, db_path)
    if user:
        if not bcrypt.checkpw(current_pw.encode(), user["password_hash"].encode()):
            flash("Current password incorrect.", "error")
            return redirect(url_for("settings.index"))

        new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
        db.update_user_password(user["id"], new_hash, db_path)
        db.audit(username, "user.change_password", "user", user["id"], db_path=db_path)
        flash("Password updated successfully.", "success")
    else:
        # Fallback to single-user config update
        from linux.routes.auth import ENV_FILE, _get_env
        from dotenv import set_key
        pw_hash = _get_env("ADMIN_PASSWORD_HASH", "")
        if pw_hash and not bcrypt.checkpw(current_pw.encode(), pw_hash.encode()):
            flash("Current password incorrect.", "error")
            return redirect(url_for("settings.index"))
        new_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
        set_key(str(ENV_FILE), "ADMIN_PASSWORD_HASH", new_hash)
        os.environ["ADMIN_PASSWORD_HASH"] = new_hash
        flash("Password updated successfully.", "success")

    return redirect(url_for("settings.index"))


@bp.route("/users/add", methods=["POST"])
@login_required
def add_user_route():
    db_path = current_app.config["DB_PATH"]
    username = request.form.get("username", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "admin")

    if not username or not password:
        flash("Username and password are required.", "error")
        return redirect(url_for("settings.index"))

    if len(password) < 8:
        flash("Password must be at least 8 characters long.", "error")
        return redirect(url_for("settings.index"))

    existing = db.get_user_by_username(username, db_path)
    if existing:
        flash(f"User '{username}' already exists.", "error")
        return redirect(url_for("settings.index"))

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    uid = db.add_user(username, pw_hash, role=role, db_path=db_path)
    db.audit(session.get("username", "admin"), "user.add", "user", uid, {"username": username, "role": role}, db_path)
    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/users/<int:uid>/delete", methods=["POST"])
@login_required
def delete_user_route(uid):
    db_path = current_app.config["DB_PATH"]
    user = db.get_user_by_id(uid, db_path)
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("settings.index"))

    if session.get("user_id") == uid:
        flash("You cannot delete your own active user account.", "error")
        return redirect(url_for("settings.index"))

    try:
        db.delete_user(uid, db_path)
        db.audit(session.get("username", "admin"), "user.delete", "user", uid, {"username": user["username"]}, db_path)
        flash(f"User '{user['username']}' deleted.", "success")
    except Exception as exc:
        flash(str(exc), "error")

    return redirect(url_for("settings.index"))


@bp.route("/pause", methods=["POST"])
@login_required
def pause():
    db_path = current_app.config["DB_PATH"]
    from linux.scheduler import pause_scheduler
    pause_scheduler(db_path)
    db.audit(session.get("username", "admin"), "scheduler.pause", db_path=db_path)
    return jsonify({"state": "PAUSED"})


@bp.route("/resume", methods=["POST"])
@login_required
def resume():
    db_path = current_app.config["DB_PATH"]
    from linux.scheduler import resume_scheduler
    resume_scheduler(db_path)
    db.audit(session.get("username", "admin"), "scheduler.resume", db_path=db_path)
    return jsonify({"state": "ACTIVE"})


@bp.route("/sync-mode", methods=["POST"])
@login_required
def sync_mode():
    db_path = current_app.config["DB_PATH"]
    token = request.form.get("confirm_token", "")
    enable = request.form.get("enable", "0") == "1"
    if enable and token != "ENABLE_SYNC_I_UNDERSTAND":
        flash("Confirmation token incorrect.", "error")
        return redirect(url_for("settings.index"))
    db.set_state_value("sync_mode_enabled", "1" if enable else "0", db_path)
    db.audit(session.get("username", "admin"), "settings.sync_mode", detail={"enabled": enable}, db_path=db_path)
    flash(f"Sync mode {'enabled' if enable else 'disabled'}.", "success")
    return redirect(url_for("settings.index"))


@bp.route("/logs")
@login_required
def app_logs():
    log_path = Path(LOG_DIR) / "app.log"
    lines = []
    if log_path.exists():
        with open(log_path) as f:
            lines = f.readlines()[-200:]
    return render_template("settings_logs.html", lines=lines)
