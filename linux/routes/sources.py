"""
linux/routes/sources.py — Source path management.
"""

from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, url_for,
)
from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("sources", __name__)


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    sources = db.get_sources("linux", db_path)
    return render_template("sources.html", sources=sources)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    db_path = current_app.config["DB_PATH"]
    data = request.form
    try:
        sid = db.add_source({
            "host": "linux",
            "name": data["name"].strip(),
            "path": data["path"].strip(),
            "data_class": data["data_class"],
            "priority": int(data.get("priority", 2)),
            "notes": data.get("notes", "").strip(),
        }, db_path)
        db.audit("admin", "source.add", "source", sid,
                 {"name": data["name"], "path": data["path"]}, db_path)
        flash(f"Source '{data['name']}' added.", "success")
    except Exception as exc:
        flash(f"Error: {exc}", "error")
    return redirect(url_for("sources.index"))


@bp.route("/<int:sid>/toggle", methods=["POST"])
@login_required
def toggle(sid):
    db_path = current_app.config["DB_PATH"]
    db.toggle_source(sid, db_path)
    return jsonify({"ok": True})


@bp.route("/<int:sid>/delete", methods=["POST"])
@login_required
def delete(sid):
    db_path = current_app.config["DB_PATH"]
    confirm = request.form.get("confirm", "")
    if confirm != "DELETE":
        flash("Type DELETE to confirm.", "error")
        return redirect(url_for("sources.index"))
    db.audit("admin", "source.delete", "source", sid, {}, db_path)
    db.delete_source(sid, db_path)
    flash("Source removed.", "success")
    return redirect(url_for("sources.index"))
