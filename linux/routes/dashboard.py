"""
linux/routes/dashboard.py — Main Dashboard Page.
"""

from flask import Blueprint, current_app, render_template
from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    rclone_conf = current_app.config.get("RCLONE_CONF", "/opt/adc-backup/rclone.conf")
    data = db.get_dashboard_data(db_path=db_path, rclone_conf=rclone_conf)
    sources = db.get_sources(host="linux", db_path=db_path)
    data["sources"] = sources
    return render_template("dashboard.html", **data)
