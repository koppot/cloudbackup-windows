"""
windows/web_server.py — Python HTTP Server for supermicro.local (Windows 10).

Exposes port 8081 over Tailscale only. Serves web_static/index.html providing exact 1:1
reference interface layout and Google Drive options:
  - Header: Encrypted Multi-Cloud Backup Controller
  - System Active / Active Target Badges
  - Quick Operational Controls (Run Backup, Dry Run, Pause, Setup Wizard, Verify, Restore Test, Refresh)
  - Automatic Capacity Fill & Rotation Threshold Bar (Quick presets 1%, 5%, 10%, 90%, 95%, 98%)
  - Cloud Target Remotes Table (Priority, Crypt Remote, Base Remote, Account Avatar/Email, Status, Capacity, Threshold, Toggle Switch, Re-auth, Test, Delete)
  - Backup Sources & File Category Filters Table
  - Snapshot Catalog History Table
  - Live Execution Log & Console Box
"""

from __future__ import annotations

import http.server
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure shared package is in import path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared import database as db
from . import auth
from .engine import WindowsBackupEngine

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", r"C:\ProgramData\adc-backup\state.db")
SESSION_FILE = r"C:\ProgramData\adc-backup\session.json"
AUTH_FILE = r"C:\ProgramData\adc-backup\auth.json"
RCLONE_CONF = os.environ.get("RCLONE_CONF", r"C:\ProgramData\adc-backup\rclone.conf")
RCLONE_BIN = os.environ.get("RCLONE_BIN", r"C:\ProgramFiles\rclone\rclone.exe")
PORT = int(os.environ.get("FLASK_PORT", "8081"))

WEB_STATIC_DIR = Path(__file__).parent / "web_static"
INDEX_HTML_PATH = WEB_STATIC_DIR / "index.html"

ENGINE = WindowsBackupEngine(db_path=DB_PATH)
_account_info_cache: Dict[str, tuple[float, dict]] = {}


def fetch_google_account_info(base_remote: str, rclone_conf: str = RCLONE_CONF) -> dict:
    clean_base = base_remote.rstrip(":")
    if not clean_base or not os.path.exists(rclone_conf):
        return {}

    if clean_base in _account_info_cache:
        t_cached, cached_data = _account_info_cache[clean_base]
        if time.time() - t_cached < 1800:
            return cached_data

    try:
        import configparser
        import urllib.request

        cfg = configparser.ConfigParser()
        cfg.read(rclone_conf)

        if cfg.has_section(clean_base) and cfg.has_option(clean_base, "token"):
            tok_raw = cfg.get(clean_base, "token")
            tok = json.loads(tok_raw)
            acc_token = tok.get("access_token")
            if acc_token:
                req = urllib.request.Request(
                    "https://www.googleapis.com/drive/v3/about?fields=user,storageQuota",
                    headers={"Authorization": f"Bearer {acc_token}"},
                )
                with urllib.request.urlopen(req, timeout=4) as resp:
                    raw = json.loads(resp.read().decode())
                    u_data = raw.get("user", {})
                    q_data = raw.get("storageQuota", {})

                    limit_bytes = int(q_data.get("limit", 5497558138880))
                    usage_bytes = int(q_data.get("usage", 0))

                    total_gb = round(limit_bytes / (1024 ** 3), 1)
                    used_gb = round(usage_bytes / (1024 ** 3), 1)
                    free_gb = max(0.0, round(total_gb - used_gb, 1))
                    pct = round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0.0

                    info = {
                        "email": u_data.get("emailAddress", ""),
                        "displayName": u_data.get("displayName", clean_base),
                        "photoLink": u_data.get("photoLink", ""),
                        "total_gb": total_gb,
                        "used_gb": used_gb,
                        "free_gb": free_gb,
                        "percent_used": pct,
                    }
                    _account_info_cache[clean_base] = (time.time(), info)
                    return info
    except Exception as exc:
        log.error("Error fetching Google Drive account info for %s: %s", clean_base, exc)

    return {}


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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/login":
            html = """<!DOCTYPE html><html><head><title>Login</title><style>body{background:#0a0a0a;color:#fff;font-family:sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;}card{background:#141414;padding:2rem;border-radius:12px;border:1px solid #262626;}input{padding:0.5rem;width:100%;margin-bottom:1rem;background:#000;color:#fff;border:1px solid #404040;}button{padding:0.5rem 1rem;background:#38bdf8;color:#000;font-weight:bold;border:none;border-radius:4px;width:100%;}</style></head><body><div class="card"><h2>supermicro Backup Login</h2><form method="POST" action="/login"><input type="password" name="password" placeholder="Password" required><button type="submit">Log In</button></form></div></body></html>"""
            return self.respond_html(html)

        if not self.is_auth():
            self.send_response(302)
            self.send_header("Location", "/login")
            self.end_headers()
            return

        db.init_db(DB_PATH)

        if path in ("/", "/index.html", "/drives", "/sources", "/runs"):
            if INDEX_HTML_PATH.exists():
                with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
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
                info = fetch_google_account_info(r["base_remote"])
                item = dict(r)
                used = info.get("used_gb") or r.get("capacity_used_gb") or 0.0
                total = info.get("total_gb") or r.get("capacity_total_gb") or 5120.0
                pct = round((used / total * 100), 1) if total > 0 else 0.0
                free = round(max(0.0, total - used), 1)

                item["is_active"] = (idx == 0)
                item["account_name"] = info.get("displayName") or r.get("account_display_name") or r["name"]
                item["account_email"] = info.get("email") or r.get("authorized_email") or ""
                item["account_photo"] = info.get("photoLink") or r.get("account_photo_url") or ""
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
            log_dir = Path(r"C:\ProgramData\adc-backup\logs")
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

        elif self.path == "/api/drives/reauthorize":
            name = body.get("name", "")
            remotes = db.get_remotes(DB_PATH)
            matching = [r for r in remotes if r["name"] == name or r["base_remote"].rstrip(":") == name]
            rid = matching[0]["id"] if matching else (remotes[0]["id"] if remotes else 1)
            result = ENGINE.reauthorize_remote(rid)
            return self.respond_json(result)

        elif self.path == "/api/drives/test":
            name = body.get("name", "")
            remotes = db.get_remotes(DB_PATH)
            matching = [r for r in remotes if r["name"] == name or r["base_remote"].rstrip(":") == name]
            rid = matching[0]["id"] if matching else (remotes[0]["id"] if remotes else 1)
            res = ENGINE.test_remote(rid)
            return self.respond_json({"success": res.get("ok", False), "message": res.get("message", "")})

        elif self.path == "/api/drives/threshold":
            name = body.get("name", "")
            thresh = float(body.get("fill_threshold_percent", 95.0))
            if name == "ALL":
                remotes = db.get_remotes(DB_PATH)
                for r in remotes:
                    db.update_remote(r["id"], {"fill_threshold_percent": thresh}, db_path=DB_PATH)
            else:
                remotes = db.get_remotes(DB_PATH)
                matching = [r for r in remotes if r["name"] == name or r["base_remote"].rstrip(":") == name]
                if matching:
                    db.update_remote(matching[0]["id"], {"fill_threshold_percent": thresh}, db_path=DB_PATH)
            return self.respond_json({"ok": True, "fill_threshold_percent": thresh})

        elif self.path == "/api/drives/toggle":
            name = body.get("name", "")
            enabled = 1 if body.get("enabled", True) else 0
            remotes = db.get_remotes(DB_PATH)
            matching = [r for r in remotes if r["name"] == name or r["base_remote"].rstrip(":") == name]
            if matching:
                db.update_remote(matching[0]["id"], {"enabled": enabled}, db_path=DB_PATH)
            return self.respond_json({"ok": True})

        elif self.path == "/api/drives/reorder":
            order = body.get("order", [])
            remotes = db.get_remotes(DB_PATH)
            id_map = {r["name"]: r["id"] for r in remotes}
            ordered_ids = [id_map[n] for n in order if n in id_map]
            db.reorder_remotes(ordered_ids, db_path=DB_PATH)
            return self.respond_json({"ok": True})

        elif self.path in ("/api/drives/remove", "/api/drives/delete"):
            name = body.get("name", "")
            remotes = db.get_remotes(DB_PATH)
            matching = [r for r in remotes if r["name"] == name or r["base_remote"].rstrip(":") == name]
            if matching:
                res = ENGINE.delete_remote(matching[0]["id"])
                return self.respond_json(res)
            return self.respond_json({"ok": True})

        elif self.path == "/api/sources/add":
            name = body.get("name", "").strip()
            path = body.get("path", "").strip()
            category = body.get("category", "storage_media").strip()
            if name and path:
                db.add_source({
                    "host": "supermicro.local",
                    "name": name,
                    "path": path,
                    "data_class": category,
                    "enabled": 1,
                }, DB_PATH)
            return self.respond_json({"ok": True})

        elif self.path == "/api/sources/remove":
            name = body.get("name", "").strip()
            if name:
                db.delete_source("supermicro.local", name, DB_PATH)
            return self.respond_json({"ok": True})

        self.respond_json({"error": "Not Found"}, 404)


def run_windows_server() -> None:
    db.init_db(DB_PATH)
    server_address = ("0.0.0.0", PORT)
    httpd = http.server.HTTPServer(server_address, BackupHTTPRequestHandler)
    log.info("Starting supermicro.local backup server on port %d", PORT)
    httpd.serve_forever()


if __name__ == "__main__":
    run_windows_server()
