"""
linux/app.py — Flask application factory for the ADC Backup Linux interface.
Version 2.4: HTTPS scheme enforcement & relaxed strict_slashes.
"""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, url_for
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv(Path(__file__).parent.parent / "config" / ".env")
load_dotenv()

DB_PATH = os.environ.get("DB_PATH", "/opt/adc-backup/db/state.db")
TAILSCALE_ONLY = os.environ.get("TAILSCALE_ONLY", "0") == "1"
TAILSCALE_INTERFACE = os.environ.get("TAILSCALE_INTERFACE", "tailscale0")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


class PrefixMiddleware:
    """WSGI middleware ensuring SCRIPT_NAME is set to /backup for all requests."""

    def __init__(self, app, prefix: str = "/backup"):
        self.app = app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_FORWARDED_PREFIX", self.prefix)
        environ["SCRIPT_NAME"] = prefix
        path_info = environ.get("PATH_INFO", "")
        if path_info.startswith(prefix):
            environ["PATH_INFO"] = path_info[len(prefix):] or "/"
        elif not path_info:
            environ["PATH_INFO"] = "/"
        # Ensure scheme is https when proxied
        if environ.get("HTTP_X_FORWARDED_PROTO") == "https":
            environ["wsgi.url_scheme"] = "https"
        return self.app(environ, start_response)


def get_tailscale_ip() -> str | None:
    """Return the first IP on the Tailscale interface, or None."""
    import netifaces
    try:
        addrs = netifaces.ifaddresses(TAILSCALE_INTERFACE)
        ipv4 = addrs.get(netifaces.AF_INET, [])
        if ipv4:
            return ipv4[0]["addr"]
    except Exception:
        pass
    try:
        ips = socket.getaddrinfo(socket.gethostname(), None)
        for _, _, _, _, addr in ips:
            if addr[0].startswith("100."):
                return addr[0]
    except Exception:
        pass
    return None


def create_app(db_path: str = DB_PATH, testing: bool = False) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Disable strict slashes globally to prevent 308 redirects from /settings to /settings/
    app.url_map.strict_slashes = False

    # ── Subpath Prefix Middleware & ProxyFix for NGINX/Apache ──
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix="/backup")
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_prefix=1,
    )

    # ── Config ──
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config["APPLICATION_ROOT"] = "/backup"
    app.config["PREFERRED_URL_SCHEME"] = "https"
    app.config["SESSION_COOKIE_NAME"] = "adc_backup_session"
    app.config["SESSION_COOKIE_PATH"] = "/backup"
    app.config["DB_PATH"] = db_path
    app.config["TESTING"] = testing
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"] = not debug_mode()
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["PERMANENT_SESSION_LIFETIME"] = 7200  # 2 hours

    # ── Init DB ──
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared.database import init_db
    init_db(db_path)

    # ── Register blueprints ──
    from linux.routes.auth import bp as auth_bp
    from linux.routes.dashboard import bp as dashboard_bp
    from linux.routes.drives import bp as drives_bp
    from linux.routes.jobs import bp as jobs_bp
    from linux.routes.runs import bp as runs_bp
    from linux.routes.restore import bp as restore_bp
    from linux.routes.sources import bp as sources_bp
    from linux.routes.settings import bp as settings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(drives_bp, url_prefix="/drives")
    app.register_blueprint(jobs_bp, url_prefix="/jobs")
    app.register_blueprint(runs_bp, url_prefix="/runs")
    app.register_blueprint(restore_bp, url_prefix="/restore")
    app.register_blueprint(sources_bp, url_prefix="/sources")
    app.register_blueprint(settings_bp, url_prefix="/settings")

    # Explicit subpath route aliases
    @app.route("/backup")
    @app.route("/backup/")
    def backup_root_alias():
        return redirect(url_for("dashboard.index"))

    # ── System status API ──
    @app.route("/api/status")
    def api_status():
        from linux.engine import get_running_job
        from shared.database import get_system_state
        return jsonify({
            "system_state": get_system_state(db_path),
            "running_job": get_running_job(),
        })

    # ── Start scheduler ──
    if not testing:
        from linux.scheduler import start as start_scheduler
        start_scheduler(db_path)

    return app


def debug_mode() -> bool:
    return os.environ.get("FLASK_DEBUG", "false").lower() == "true"


def run_server() -> None:
    """Entry point: bind to loopback 127.0.0.1 for NGINX/Apache proxying."""
    app = create_app()
    host = os.environ.get("FLASK_HOST")
    port = int(os.environ.get("FLASK_PORT", "8765"))
    debug = debug_mode()

    if TAILSCALE_ONLY and not debug:
        ts_ip = get_tailscale_ip()
        if not ts_ip:
            log.critical("TAILSCALE_ONLY=1 but no Tailscale IP found. Refusing to start.")
            raise SystemExit(1)
        host = ts_ip
        log.info("Binding to Tailscale IP: %s", host)
    else:
        host = host or "127.0.0.1"

    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve
        log.info("Starting ADC Backup UI on http://%s:%d (Behind Proxy /backup)", host, port)
        serve(app, host=host, port=port, threads=4)


if __name__ == "__main__":
    run_server()
