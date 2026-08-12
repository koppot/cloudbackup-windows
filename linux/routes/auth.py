"""
linux/routes/auth.py — Login, TOTP, multi-user authentication, and logout.
"""

from __future__ import annotations

import io
import os
from functools import wraps
from pathlib import Path

import bcrypt
import pyotp
import qrcode
from dotenv import load_dotenv, set_key
from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for, send_file, jsonify,
)
from shared import database as db

bp = Blueprint("auth", __name__)

ENV_FILE = Path(__file__).parent.parent.parent / "config" / ".env"


def _get_env(key: str, default: str = "") -> str:
    load_dotenv(ENV_FILE)
    return os.environ.get(key, default)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authed"):
            is_api = (
                request.is_json
                or request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or "/api/" in request.path
                or "/status" in request.path
                or "/start-auto" in request.path
                or "/suggest-next" in request.path
            )
            if is_api:
                return jsonify({"error": "unauthorized", "login_url": url_for("auth.login")}), 401
            next_url = url_for(request.endpoint or "dashboard.index", **request.view_args) if request.endpoint else url_for("dashboard.index")
            return redirect(url_for("auth.login", next=next_url))
        return f(*args, **kwargs)
    return decorated


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authed"):
        return redirect(url_for("dashboard.index"))

    db_path = current_app.config["DB_PATH"]
    error = None

    if request.method == "POST":
        username = request.form.get("username", "admin").strip().lower()
        password = request.form.get("password", "")

        user = db.get_user_by_username(username, db_path)
        if user:
            if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
                session["pw_ok"] = True
                session["pending_user_id"] = user["id"]
                session["pending_username"] = user["username"]
                session["pending_role"] = user["role"]
                totp_secret = user.get("totp_secret") or _get_env("TOTP_SECRET", "")
                session["pending_totp_secret"] = totp_secret
                session.modified = True
                if not totp_secret:
                    return redirect(url_for("auth.totp_setup"))
                return redirect(url_for("auth.totp_verify", next=request.args.get("next")))
            else:
                error = "Invalid username or password."
        else:
            pw_hash = _get_env("ADMIN_PASSWORD_HASH", "")
            if pw_hash and bcrypt.checkpw(password.encode(), pw_hash.encode()):
                session["pw_ok"] = True
                session["pending_username"] = username or "admin"
                session["pending_role"] = "admin"
                totp_secret = _get_env("TOTP_SECRET", "")
                session["pending_totp_secret"] = totp_secret
                session.modified = True
                if not totp_secret:
                    return redirect(url_for("auth.totp_setup"))
                return redirect(url_for("auth.totp_verify", next=request.args.get("next")))
            else:
                error = "Invalid username or password."

    return render_template("login.html", error=error)


@bp.route("/totp", methods=["GET", "POST"])
def totp_verify():
    if not session.get("pw_ok"):
        return redirect(url_for("auth.login"))

    error = None
    totp_secret = session.get("pending_totp_secret") or _get_env("TOTP_SECRET", "")

    if request.method == "POST":
        code = request.form.get("code", "").strip()
        totp = pyotp.TOTP(totp_secret)
        if totp.verify(code, valid_window=1):
            session.permanent = True
            session["authed"] = True
            session["username"] = session.get("pending_username", "admin")
            session["role"] = session.get("pending_role", "admin")
            if "pending_user_id" in session:
                session["user_id"] = session.get("pending_user_id")

            session.pop("pw_ok", None)
            session.pop("pending_user_id", None)
            session.pop("pending_username", None)
            session.pop("pending_role", None)
            session.pop("pending_totp_secret", None)
            session.modified = True

            next_url = request.args.get("next")
            if not next_url or not next_url.startswith("/backup"):
                next_url = url_for("dashboard.index")

            return redirect(next_url)
        else:
            error = "Invalid or expired TOTP code."

    return render_template("totp_verify.html", error=error)


@bp.route("/totp/setup", methods=["GET", "POST"])
def totp_setup():
    if not session.get("pw_ok"):
        return redirect(url_for("auth.login"))

    db_path = current_app.config["DB_PATH"]
    user_id = session.get("pending_user_id")

    if request.method == "POST":
        secret = request.form.get("secret", "")
        code = request.form.get("code", "")
        totp = pyotp.TOTP(secret)
        if totp.verify(code, valid_window=1):
            if user_id:
                db.update_user_totp(user_id, secret, db_path)
            else:
                ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
                set_key(str(ENV_FILE), "TOTP_SECRET", secret)
                os.environ["TOTP_SECRET"] = secret

            session.permanent = True
            session["authed"] = True
            session["username"] = session.get("pending_username", "admin")
            session["role"] = session.get("pending_role", "admin")
            if user_id:
                session["user_id"] = user_id

            session.pop("pw_ok", None)
            session.pop("pending_user_id", None)
            session.pop("pending_username", None)
            session.pop("pending_role", None)
            session.pop("pending_totp_secret", None)
            session.modified = True

            flash("TOTP configured successfully.", "success")
            return redirect(url_for("dashboard.index"))
        else:
            flash("TOTP code did not match.", "error")
            return redirect(url_for("auth.totp_setup"))

    secret = pyotp.random_base32()
    issuer = "ADC Backup"
    username = session.get("pending_username", "admin")
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)
    return render_template("totp_setup.html", secret=secret, uri=uri)


@bp.route("/totp/qr.png")
def totp_qr():
    uri = request.args.get("uri", "")
    if not uri:
        return "", 400
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
