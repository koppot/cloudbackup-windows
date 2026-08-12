"""
linux/routes/drives.py — Google Drive Remote Management matching Windows authorization flow and settings.
Uses rclone's native loopback authorization listener (127.0.0.1:53682) over SSH local tunnel.
Exact Windows-parity for Google Drive settings, rotation thresholds, and rclone performance options.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)

from linux.routes.auth import login_required
from shared import database as db

bp = Blueprint("drives", __name__)
log = logging.getLogger(__name__)

RCLONE_BIN = os.environ.get("RCLONE_BIN", "/usr/bin/rclone")
RCLONE_CONF = os.environ.get("RCLONE_CONF", "/opt/adc-backup/rclone.conf")

_active_auth_lock = threading.Lock()
_active_auth_proc: subprocess.Popen | None = None


def _obscure_password(password: str) -> str:
    try:
        res = subprocess.run([RCLONE_BIN, "obscure", password], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return password


def _append_rclone_stanzas(base_name: str, token_json: str, pass1: str, pass2: str, data_folder_id: str = "", secrets_folder_id: str = "") -> tuple[str, str, str]:
    base_remote = f"{base_name}:"
    crypt_remote = f"{base_name}_crypt:"
    secrets_crypt_remote = f"{base_name}_secrets_crypt:"

    obs1 = _obscure_password(pass1)
    obs2 = _obscure_password(pass2)

    root_id_line = f"root_folder_id = {data_folder_id}\n" if data_folder_id else ""
    secrets_root_id_line = f"root_folder_id = {secrets_folder_id}\n" if secrets_folder_id else ""
    remote_target = f"{base_name}:" if data_folder_id else f"{base_name}:adc-backup-data"
    secrets_remote_target = f"{base_name}:" if secrets_folder_id else f"{base_name}:adc-backup-secrets"

    stanzas = f"""
[{base_name}]
type = drive
scope = drive
{root_id_line}token = {token_json.strip()}

[{base_name}_crypt]
type = crypt
remote = {remote_target}
filename_encryption = standard
directory_name_encryption = true
password = {obs1}

[{base_name}_secrets_crypt]
type = crypt
remote = {secrets_remote_target}
filename_encryption = standard
directory_name_encryption = true
password = {obs2}
"""
    conf_path = Path(RCLONE_CONF)
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    with open(conf_path, "a") as f:
        f.write(stanzas)

    try:
        os.chmod(conf_path, 0o600)
    except Exception:
        pass

    return base_remote, crypt_remote, secrets_crypt_remote


def _run_rclone_mkdir(remote_folder: str) -> bool:
    cmd = [RCLONE_BIN, "--config", RCLONE_CONF, "mkdir", remote_folder]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        return res.returncode == 0
    except Exception:
        return False


def _get_folder_id(base_name: str, folder_name: str) -> str:
    cmd = [RCLONE_BIN, "--config", RCLONE_CONF, "lsf", f"{base_name}:", "--format", "pi"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if ";" in line:
                    path, fid = line.strip().split(";", 1)
                    if path.rstrip("/") == folder_name:
                        return fid
    except Exception:
        pass
    return ""


def _auto_register_drive_from_token(token_data: dict, db_path: str, custom_name: str = "") -> dict:
    access_token = token_data.get("access_token")

    if not custom_name:
        remotes = db.get_remotes(db_path)
        next_idx = len(remotes) + 1
        name = f"gdrive{next_idx}"
    else:
        name = custom_name.strip()

    pass1 = "SuperMicroBackup2026!Secure"
    pass2 = secrets.token_urlsafe(24)

    _run_rclone_mkdir(f"{name}:adc-backup-data")
    _run_rclone_mkdir(f"{name}:adc-backup-secrets")

    data_folder_id = _get_folder_id(name, "adc-backup-data")
    secrets_folder_id = _get_folder_id(name, "adc-backup-secrets")

    base_remote, crypt_remote, secrets_crypt_remote = _append_rclone_stanzas(
        name, json.dumps(token_data), pass1, pass2, data_folder_id, secrets_folder_id
    )


    user_email = ""
    display_name = ""
    photo_url = ""
    if access_token:
        try:
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                info = resp.json()
                user_email = info.get("email", "")
                display_name = info.get("name", "")
                photo_url = info.get("picture", "")
        except Exception:
            pass

    priority = len(db.get_remotes(db_path)) + 1
    rid = db.add_remote({
        "name": name,
        "provider": "drive",
        "base_remote": base_remote,
        "crypt_remote": crypt_remote,
        "secrets_crypt_remote": secrets_crypt_remote,
        "priority": priority,
        "authorized_email": user_email,
        "account_display_name": display_name,
        "account_photo_url": photo_url,
        "authorized_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok",
    }, db_path)

    log.info("Google Drive remote %s registered successfully for account %s", name, user_email or "unknown")

    return {
        "remote_id": rid,
        "name": name,
        "email": user_email,
        "display_name": display_name,
    }


def _background_authorize_listener(proc: subprocess.Popen, name: str, db_path: str):
    try:
        out, _ = proc.communicate(timeout=180)
        match = re.search(r'(\{.*"access_token".*\})', out, re.DOTALL)
        if match:
            token_data = json.loads(match.group(1))
            _auto_register_drive_from_token(token_data, db_path, name)
            log.info("Loopback authorization succeeded for %s", name)
    except Exception as exc:
        log.error("Error in background rclone authorize listener for %s: %s", name, exc)
        try:
            proc.kill()
        except Exception:
            pass


@bp.route("/")
@login_required
def index():
    db_path = current_app.config["DB_PATH"]
    rclone_conf = current_app.config.get("RCLONE_CONF", "/opt/adc-backup/rclone.conf")
    remotes = db.get_remotes(db_path)
    settings = db.get_settings(db_path)

    from shared.google_account import fetch_google_account_info

    enriched_remotes = []
    for r in remotes:
        item = dict(r)
        base = item.get("base_remote", "").rstrip(":")
        acc = fetch_google_account_info(base, rclone_conf)

        item["authorized_email"] = acc.get("email") or item.get("authorized_email") or "Google Account"
        item["account_display_name"] = acc.get("displayName") or item.get("account_display_name") or item.get("name")
        item["account_photo_url"] = acc.get("photoLink") or item.get("account_photo_url") or ""

        cap = acc.get("capacity", {})
        item["capacity_total_gb"] = cap.get("total_gb") or item.get("capacity_total_gb") or 5120.0
        item["capacity_used_gb"] = cap.get("used_gb") if cap.get("used_gb") is not None else (item.get("capacity_used_gb") or 0.0)
        item["percent_used"] = cap.get("percent_used") or 0.0
        item["free_gb"] = cap.get("free_gb") or round(max(0.0, item["capacity_total_gb"] - item["capacity_used_gb"]), 1)

        enriched_remotes.append(item)

    next_idx = len(enriched_remotes) + 1
    next_suggested = {
        "name": f"gdrive{next_idx}",
        "base_remote": f"gdrive{next_idx}:",
        "crypt_remote": f"gdrive{next_idx}_crypt:",
        "secrets_crypt_remote": f"gdrive{next_idx}_secrets_crypt:",
        "priority": next_idx,
    }
    return render_template(
        "drives.html",
        remotes=enriched_remotes,
        settings=settings,
        next_suggested=next_suggested,
    )



@bp.route("/suggest-next")
@login_required
def suggest_next():
    remotes = db.get_remotes(current_app.config["DB_PATH"])
    next_idx = len(remotes) + 1
    return jsonify({
        "name": f"gdrive{next_idx}",
        "base_remote": f"gdrive{next_idx}:",
        "crypt_remote": f"gdrive{next_idx}_crypt:",
        "secrets_crypt_remote": f"gdrive{next_idx}_secrets_crypt:",
        "priority": next_idx,
    })


@bp.route("/global-settings", methods=["POST"])
@login_required
def update_global_settings():
    db_path = current_app.config["DB_PATH"]
    data = request.form
    pairs = {
        "reserve_margin_percent": str(float(data.get("reserve_margin_percent", 5.0))),
        "reserve_margin_gb": str(float(data.get("reserve_margin_gb", 10.0))),
        "rclone_tpslimit": str(int(data.get("rclone_tpslimit", 10))),
        "rclone_tpslimit_burst": str(int(data.get("rclone_tpslimit_burst", 10))),
        "rclone_transfers": str(int(data.get("rclone_transfers", 4))),
        "rclone_checkers": str(int(data.get("rclone_checkers", 8))),
        "rclone_bwlimit": data.get("rclone_bwlimit", "5M").strip(),
        "rclone_chunk_size": data.get("rclone_chunk_size", "64M").strip(),
        "rclone_retries": str(int(data.get("rclone_retries", 5))),
        "rclone_low_level_retries": str(int(data.get("rclone_low_level_retries", 10))),
        "rclone_fast_list": "1" if data.get("rclone_fast_list") else "0",
    }
    db.update_settings(pairs, db_path)
    db.audit(session.get("username", "admin"), "drives.update_global_settings", detail=pairs, db_path=db_path)
    flash("Windows-parity Google Drive & rclone settings updated.", "success")
    return redirect(url_for("drives.index"))


@bp.route("/oauth/connect")
@login_required
def oauth_connect():
    """
    Automated Google OAuth Flow matching Windows authorization architecture.
    Starts rclone's native loopback listener on 127.0.0.1:53682 and redirects browser directly.
    """
    global _active_auth_proc
    db_path = current_app.config["DB_PATH"]
    custom_name = request.args.get("name", "").strip()

    with _active_auth_lock:
        subprocess.run(["pkill", "-f", "rclone authorize"], capture_output=True)

        proc = subprocess.Popen(
            [RCLONE_BIN, "authorize", "drive"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _active_auth_proc = proc

        auth_url = None
        start = time.time()
        while time.time() - start < 5:
            line = proc.stdout.readline()
            if "http://127.0.0.1:53682/" in line or "accounts.google.com" in line:
                match = re.search(r'(https?://[^\s]+)', line)
                if match:
                    auth_url = match.group(1)
                    break
            time.sleep(0.05)

        if not auth_url:
            auth_url = "http://127.0.0.1:53682/auth"

        t = threading.Thread(
            target=_background_authorize_listener,
            args=(proc, custom_name, db_path),
            daemon=True,
        )
        t.start()

    return redirect(auth_url)


@bp.route("/add", methods=["POST"])
@login_required
def add():
    data = request.form
    db_path = current_app.config["DB_PATH"]
    try:
        rid = db.add_remote({
            "name": data["name"].strip(),
            "provider": data.get("provider", "drive").strip(),
            "base_remote": data["base_remote"].strip().rstrip(":") + ":",
            "crypt_remote": data["crypt_remote"].strip().rstrip(":") + ":",
            "secrets_crypt_remote": data.get("secrets_crypt_remote", "").strip() or None,
            "priority": int(data.get("priority", 1)),
            "fill_threshold_percent": float(data.get("fill_threshold_percent", 95.0)),
            "authorized_email": data.get("authorized_email", "").strip(),
            "notes": data.get("notes", "").strip(),
        }, db_path)
        db.audit(session.get("username", "admin"), "remote.add", "remote", rid, {"name": data["name"]}, db_path)
        flash(f"Drive '{data['name']}' added.", "success")
    except Exception as exc:
        flash(f"Error adding drive: {exc}", "error")
    return redirect(url_for("drives.index"))


@bp.route("/<int:rid>/toggle", methods=["POST"])
@login_required
def toggle(rid):
    db_path = current_app.config["DB_PATH"]
    remote = db.get_remote(rid, db_path)
    if not remote:
        return jsonify({"error": "not found"}), 404
    new_val = 0 if remote["enabled"] else 1
    db.update_remote(rid, {"enabled": new_val}, db_path)
    db.audit(session.get("username", "admin"), "remote.toggle", "remote", rid, {"enabled": new_val}, db_path)
    return jsonify({"enabled": new_val})


@bp.route("/<int:rid>/delete", methods=["POST"])
@login_required
def delete(rid):
    db_path = current_app.config["DB_PATH"]
    remote = db.get_remote(rid, db_path)
    confirm = request.form.get("confirm_name", "").strip()
    if not remote:
        flash("Remote not found.", "error")
        return redirect(url_for("drives.index"))
    if confirm != remote["name"]:
        flash("Confirmation name did not match. Drive not deleted.", "error")
        return redirect(url_for("drives.index"))
    jobs = db.get_jobs("linux", db_path)
    if any(j["remote_id"] == rid for j in jobs):
        flash("Cannot delete: active jobs reference this drive. Disable them first.", "error")
        return redirect(url_for("drives.index"))
    db.audit(session.get("username", "admin"), "remote.delete", "remote", rid, {"name": remote["name"]}, db_path)
    db.delete_remote(rid, db_path)
    flash(f"Drive '{remote['name']}' deleted.", "success")
    return redirect(url_for("drives.index"))


@bp.route("/<int:rid>/threshold", methods=["POST"])
@login_required
def set_threshold(rid):
    db_path = current_app.config["DB_PATH"]
    val = float(request.form.get("threshold", 95.0))
    val = max(50.0, min(99.0, val))
    db.update_remote(rid, {"fill_threshold_percent": val}, db_path)
    return jsonify({"fill_threshold_percent": val})


@bp.route("/reorder", methods=["POST"])
@login_required
def reorder():
    db_path = current_app.config["DB_PATH"]
    ordered_ids = request.json.get("ordered_ids", [])
    db.reorder_remotes([int(i) for i in ordered_ids], db_path)
    db.audit(session.get("username", "admin"), "remote.reorder", detail={"ordered_ids": ordered_ids}, db_path=db_path)
    return jsonify({"ok": True})


@bp.route("/<int:rid>/test", methods=["POST"])
@login_required
def test_connection(rid):
    db_path = current_app.config["DB_PATH"]
    remote = db.get_remote(rid, db_path)
    if not remote:
        return jsonify({"error": "not found"}), 404
    base = remote["base_remote"].rstrip(":") + ":"
    try:
        result = subprocess.run(
            [RCLONE_BIN, "lsd", base, "--config", RCLONE_CONF, "--max-depth", "1"],
            capture_output=True, text=True, timeout=30,
        )
        ok = result.returncode == 0
        db.update_remote(rid, {"status": "ok" if ok else "error"}, db_path)
        return jsonify({"ok": ok, "output": (result.stdout + result.stderr)[-500:]})
    except Exception as exc:
        return jsonify({"ok": False, "output": str(exc)})


@bp.route("/<int:rid>/refresh-quota", methods=["POST"])
@login_required
def refresh_quota(rid):
    db_path = current_app.config["DB_PATH"]
    remote = db.get_remote(rid, db_path)
    if not remote:
        return jsonify({"error": "not found"}), 404
    base = remote["base_remote"].rstrip(":") + ":"
    try:
        result = subprocess.run(
            [RCLONE_BIN, "about", base, "--config", RCLONE_CONF, "--json"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            info = json.loads(result.stdout)
            total = info.get("total", 0) / (1024**3)
            used = info.get("used", 0) / (1024**3)
            db.update_remote(rid, {
                "capacity_total_gb": round(total, 2),
                "capacity_used_gb": round(used, 2),
                "capacity_checked_at": datetime.now(timezone.utc).isoformat(),
                "status": "ok",
            }, db_path)
            return jsonify({"total_gb": round(total, 2), "used_gb": round(used, 2)})
        return jsonify({"error": result.stderr[-200:]}), 500
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
