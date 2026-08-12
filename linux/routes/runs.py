"""
linux/routes/runs.py — Immutable run history.
"""

from flask import Blueprint, current_app, abort, render_template, request, send_file
from linux.routes.auth import login_required
from shared import database as db
from pathlib import Path

bp = Blueprint("runs", __name__)


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    page = int(request.args.get("page", 1))
    limit = 25
    offset = (page - 1) * limit
    status_filter = request.args.get("status", "")
    job_id = request.args.get("job_id", type=int)
    runs = db.get_runs(job_id=job_id, limit=limit, offset=offset,
                       status=status_filter or None, db_path=db_path)
    jobs = db.get_jobs("linux", db_path)
    return render_template("runs.html", runs=runs, jobs=jobs, page=page,
                           status_filter=status_filter, job_id=job_id)


@bp.route("/<int:run_id>")
@login_required
def detail(run_id):
    db_path = current_app.config["DB_PATH"]
    run = db.get_run(run_id, db_path)
    if not run:
        abort(404)
    log_tail = []
    targets = db.get_run_targets(run_id, db_path)
    for t in targets:
        lpath = t.get("log_path")
        if lpath and Path(lpath).exists():
            try:
                lines = Path(lpath).read_text(errors="replace").splitlines()
                log_tail.append(f"=== Target Remote: {t.get('remote_name', t.get('remote_id'))} [{t.get('status')}] ===")
                log_tail.extend(lines[-100:])
            except Exception:
                pass

    if not log_tail and run.get("log_path") and Path(run["log_path"]).exists():
        with open(run["log_path"]) as f:
            lines = f.readlines()
        log_tail = [l.strip() for l in lines[-200:]]

    return render_template("run_detail.html", run=run, targets=targets, log_tail=log_tail)



@bp.route("/<int:run_id>/log")
@login_required
def view_log(run_id):
    db_path = current_app.config["DB_PATH"]
    run = db.get_run(run_id, db_path)
    if not run or not run["log_path"]:
        abort(404)
    log_path = Path(run["log_path"])
    if not log_path.exists():
        abort(404)
    lines = log_path.read_text(errors="replace")
    return render_template("run_log.html", run=run, log_content=lines)


@bp.route("/<int:run_id>/download-log")
@login_required
def download_log(run_id):
    db_path = current_app.config["DB_PATH"]
    run = db.get_run(run_id, db_path)
    if not run or not run["log_path"]:
        abort(404)
    return send_file(run["log_path"], as_attachment=True,
                     download_name=f"run-{run_id}.log")


@bp.route("/logs/latest")
@login_required
def latest_log():
    db_path = current_app.config["DB_PATH"]
    runs = db.get_runs(limit=1, db_path=db_path)
    if not runs:
        return {"logs": "No runs recorded yet."}
    run = runs[0]

    # Collect log lines from target workers
    targets = db.get_run_targets(run["id"], db_path)
    log_content = []
    for t in targets:
        lpath = t.get("log_path")
        if lpath and Path(lpath).exists():
            try:
                lines = Path(lpath).read_text(errors="replace").splitlines()
                log_content.append(f"=== Target Remote: {t.get('remote_name', t.get('remote_id'))} [{t.get('status')}] ===")
                log_content.extend(lines[-30:])
            except Exception:
                pass

    if not log_content and run.get("log_path") and Path(run["log_path"]).exists():
        try:
            log_content = Path(run["log_path"]).read_text(errors="replace").splitlines()[-100:]
        except Exception:
            pass

    return {"logs": "\n".join(log_content) if log_content else "Live console waiting for active worker stream..."}


