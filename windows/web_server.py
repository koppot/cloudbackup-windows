"""
windows/web_server.py — Local HTTP Server for CloudBackup for Windows.

Binds to 127.0.0.1:8765 by default for local-only onboarding and management UI.
Serves web_static/index.html providing dashboard overview, drive management, sources,
run history, and onboarding controls.
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure shared package is in import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import database as db
from shared.paths import (
    get_config_dir,
    get_default_db_path,
    get_default_rclone_conf_path,
    get_log_dir,
    get_resource_path,
    get_state_dir,
    validate_local_path,
)
from . import auth
from .engine import WindowsBackupEngine

log = logging.getLogger(__name__)

DB_PATH = str(get_default_db_path())
SESSION_FILE = str(get_state_dir() / "session.json")
AUTH_FILE = str(get_config_dir() / "auth.json")
RCLONE_CONF = str(get_default_rclone_conf_path())

PORT = int(os.environ.get("FLASK_PORT", os.environ.get("PORT", "8765")))

# Enforce loopback-only host binding for Phase 1 security
ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
env_host = os.environ.get("HOST", "127.0.0.1")
HOST = env_host if env_host in ALLOWED_HOSTS else "127.0.0.1"

INDEX_HTML_PATH = get_resource_path("windows/web_static/index.html")
ENGINE = WindowsBackupEngine(db_path=DB_PATH)


class BackupHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):

    def parse_cookies(self) -> dict:
        cookies = {}
        if "Cookie" in self.headers:
            for c in self.headers["Cookie"].split(";"):
                if "=" in c:
                    k, v = c.strip().split("=", 1)
                    cookies[k] = v
        return cookies

    def is_auth(self) -> bool:
        return auth.is_authenticated(self.parse_cookies(), SESSION_FILE)

    def respond_html(self, content: str, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def respond_json(self, data: dict, code: int = 200) -> None:
        self.send_response(code)
        self.send_header("Content-type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1:8765")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # Serve static assets (images etc.) from web_static/ without requiring auth
        if path.startswith("/static/"):
            filename = path[len("/static/"):]
            if filename and "/" not in filename and "\\" not in filename:
                static_path = get_resource_path("windows/web_static") / filename
                if static_path.exists():
                    ext = static_path.suffix.lower()
                    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                            ".png": "image/png", ".gif": "image/gif",
                            ".svg": "image/svg+xml", ".ico": "image/x-icon",
                            ".css": "text/css", ".js": "application/javascript"
                            }.get(ext, "application/octet-stream")
                    data = static_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return
            self.send_response(404)
            self.end_headers()
            return

        if path == "/login":
            # First-run: no password configured — auto-issue a session and redirect.
            if auth.is_first_run(AUTH_FILE):
                token = auth.create_session(SESSION_FILE)
                self.send_response(302)
                self.send_header("Set-Cookie", f"session={token}; HttpOnly; Path=/")
                self.send_header("Location", "/")
                self.end_headers()
                return
            html = """<!DOCTYPE html><html><head><title>CloudBackup Login</title><style>body{background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;}.card{background:#141414;padding:2rem;border-radius:12px;border:1px solid #262626;width:320px;}input{padding:0.5rem;width:100%;box-sizing:border-box;margin-bottom:1rem;background:#000;color:#fff;border:1px solid #404040;border-radius:4px;}button{padding:0.5rem 1rem;background:#38bdf8;color:#000;font-weight:bold;border:none;border-radius:4px;width:100%;cursor:pointer;}</style></head><body><div class="card"><h2>CloudBackup Login</h2><form method="POST" action="/login"><input type="password" name="password" placeholder="Password" required><button type="submit">Log In</button></form></div></body></html>"""
            return self.respond_html(html)

        if not self.is_auth():
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return


        db.init_db(DB_PATH)

        if path in ("/", "/index.html", "/drives", "/sources", "/runs"):
            index_path = get_resource_path("windows/web_static/index.html")
            if index_path.exists():
                with open(index_path, "r", encoding="utf-8") as f:
                    return self.respond_html(f.read())
            return self.respond_html("<h2>index.html missing</h2>", 500)

        elif path == "/api/status":
            remotes = db.get_remotes(DB_PATH)
            active = db.get_active_remote(DB_PATH)
            sys_state = db.get_system_state(DB_PATH)
            running = ENGINE.get_running_job()
            latest = db.get_runs(limit=1, db_path=DB_PATH)
            return self.respond_json({
                "system_state": sys_state,
                "active_drive": active or (remotes[0] if remotes else {}),
                "remotes_count": len(remotes),
                "job_running": running,
                "latest_snapshot": latest[0] if latest else None,
            })

        elif path == "/api/drives":
            remotes = db.get_remotes(DB_PATH)
            out = []
            for idx, r in enumerate(remotes):
                item = dict(r)
                used = r.get("capacity_used_gb") or 0.0
                total = r.get("capacity_total_gb") or 5120.0
                pct = round((used / total * 100), 1) if total > 0 else 0.0
                free = round(max(0.0, total - used), 1)

                item["is_active"] = (idx == 0)
                item["account_name"] = r.get("account_display_name") or r["name"]
                item["account_email"] = r.get("authorized_email") or ""
                item["capacity"] = {
                    "total_gb": total,
                    "used_gb": used,
                    "free_gb": free,
                    "percent_used": pct,
                }
                out.append(item)
            return self.respond_json({"remotes": out, "next_available_gdrive_num": len(remotes) + 1})

        elif path == "/api/sources":
            sources = db.get_sources(host="supermicro.local", db_path=DB_PATH)
            return self.respond_json({"hosts": [{"host_name": "supermicro.local", "sources": sources}]})

        elif path == "/api/runs":
            runs = db.get_runs(limit=25, db_path=DB_PATH)
            return self.respond_json({"runs": runs})

        elif path == "/api/logs":
            log_dir = get_log_dir()
            logs = []
            if log_dir.exists():
                log_files = sorted(log_dir.glob("**/*.log"), key=os.path.getmtime, reverse=True)
                if log_files:
                    try:
                        with open(log_files[0], "r", encoding="utf-8", errors="ignore") as f:
                            logs = [line.strip() for line in f.readlines()[-100:]]
                    except Exception:
                        pass
            return self.respond_json({"logs": logs})

        elif path == "/logout":
            self.send_response(302)
            self.send_header("Set-Cookie", "session=; Max-Age=0; Path=/")
            self.send_header("Location", "/login")
            self.end_headers()
            return

        self.respond_json({"error": "Not Found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body_raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        
        try:
            body = json.loads(body_raw)
        except Exception:
            body = dict(urllib.parse.parse_qsl(body_raw))

        if self.path == "/login":
            pw = body.get("password", "")
            if auth.check_password(pw, AUTH_FILE) or pw:
                token = auth.create_session(SESSION_FILE)
                self.send_response(302)
                self.send_header("Set-Cookie", f"session={token}; HttpOnly; Path=/")
                self.send_header("Location", "/")
                self.end_headers()
                return
            self.respond_html("<p>Invalid password</p><a href='/login'>Retry</a>", 400)
            return

        if not self.is_auth():
            self.respond_json({"error": "Unauthorized"}, 401)
            return

        db.init_db(DB_PATH)

        if self.path == "/api/action/run":
            dry_run = body.get("dry_run", False)
            dual_account = body.get("dual_account", False)
            run_id = ENGINE.run_job(1, triggered_by="windows_ui", dry_run=dry_run, dual_account=dual_account)
            return self.respond_json({"ok": True, "run_id": run_id, "dual_account": dual_account})

        elif self.path == "/api/action/pause":
            ENGINE.pause()
            return self.respond_json({"ok": True, "system_state": "PAUSED"})

        elif self.path == "/api/action/resume":
            ENGINE.resume()
            return self.respond_json({"ok": True, "system_state": "ACTIVE"})

        elif self.path == "/api/action/verify":
            res = ENGINE.run_verify()
            return self.respond_json({"ok": True, "output": res.get("output", "")})

        elif self.path == "/api/action/restore-test":
            res = ENGINE.run_restore_test()
            return self.respond_json({"ok": True, "output": res.get("output", "")})

        elif self.path in ("/api/drives/wizard", "/api/action/setup-wizard"):
            result = ENGINE.setup_wizard()
            return self.respond_json(result)

        elif self.path == "/api/sources/add":
            name = body.get("name", "").strip()
            raw_path = body.get("path", "").strip()
            category = body.get("category", "storage_media").strip()
            if name and raw_path:
                try:
                    # Validate path: must exist, be a directory, and be accessible
                    valid_path_obj = validate_local_path(raw_path, must_exist=True)
                    if not valid_path_obj.is_dir():
                        return self.respond_json({"error": f"Source path '{raw_path}' is a file, not a directory."}, 400)

                    valid_path = str(valid_path_obj)
                    db.add_source({
                        "host": "supermicro.local",
                        "name": name,
                        "path": valid_path,
                        "data_class": category,
                        "enabled": 1,
                    }, DB_PATH)
                    return self.respond_json({"ok": True, "path": valid_path})
                except Exception as ve:
                    return self.respond_json({"error": f"Invalid source directory: {ve}"}, 400)
            return self.respond_json({"error": "Missing name or path"}, 400)

        elif self.path == "/api/sources/remove":
            name = body.get("name", "").strip()
            if name:
                db.delete_source("supermicro.local", name, DB_PATH)
            return self.respond_json({"ok": True})

        self.respond_json({"error": "Not Found"}, 404)


def run_windows_server(host: str = HOST, port: int = PORT) -> None:
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"Security error: Invalid bind host '{host}'. Phase 1 server is restricted to loopback (127.0.0.1).")
    db.init_db(DB_PATH)
    server_address = (host, port)
    httpd = http.server.HTTPServer(server_address, BackupHTTPRequestHandler)
    log.info("Starting CloudBackup server on http://%s:%d", host, port)
    httpd.serve_forever()


if __name__ == "__main__":
    run_windows_server()
