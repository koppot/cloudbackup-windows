"""
shared/database.py — SQLite database access layer for CloudBackup for Windows.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.environ.get("DB_PATH", r"C:\ProgramData\CloudBackup\state.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"



def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@contextmanager
def get_conn(db_path: str = DEFAULT_DB_PATH) -> Generator[sqlite3.Connection, None, None]:
    """Yield a WAL-mode SQLite connection with row_factory set."""
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str = DEFAULT_DB_PATH) -> None:
    """Create all tables from schema.sql if they do not exist."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    schema = SCHEMA_PATH.read_text()
    with get_conn(db_path) as conn:
        conn.executescript(schema)
    log.info("Database initialised at %s", db_path)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _row(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Optional[dict]:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ─── system_state ─────────────────────────────────────────────────────────────

def get_system_state(db_path: str = DEFAULT_DB_PATH) -> str:
    with get_conn(db_path) as conn:
        row = _row(conn, "SELECT value FROM system_state WHERE key='state'")
    return row["value"] if row else "ACTIVE"


def set_system_state(state: str, db_path: str = DEFAULT_DB_PATH) -> None:
    assert state in ("ACTIVE", "PAUSED"), f"Invalid state: {state}"
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO system_state(key,value,updated_at) VALUES('state',?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (state, _now()),
        )


def get_state_value(key: str, db_path: str = DEFAULT_DB_PATH) -> Optional[str]:
    with get_conn(db_path) as conn:
        row = _row(conn, "SELECT value FROM system_state WHERE key=?", (key,))
    return row["value"] if row else None


def set_state_value(key: str, value: str, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO system_state(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now()),
        )


# ─── settings ─────────────────────────────────────────────────────────────────

def get_settings(db_path: str = DEFAULT_DB_PATH) -> dict[str, str]:
    with get_conn(db_path) as conn:
        rows = _rows(conn, "SELECT key, value FROM settings")
    return {r["key"]: r["value"] or "" for r in rows}


def get_setting(key: str, default: str = "", db_path: str = DEFAULT_DB_PATH) -> str:
    with get_conn(db_path) as conn:
        row = _row(conn, "SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row and row["value"] is not None else default


def set_setting(key: str, value: str, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now()),
        )


def update_settings(pairs: dict[str, str], db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        for key, value in pairs.items():
            conn.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, _now()),
            )


# ─── remotes ──────────────────────────────────────────────────────────────────

def get_remotes(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, "SELECT * FROM remotes ORDER BY priority, id")


def get_remote(remote_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        return _row(conn, "SELECT * FROM remotes WHERE id=?", (remote_id,))


def get_active_remotes(count: int = 2, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return top N active, non-full remotes ordered by priority."""
    with get_conn(db_path) as conn:
        return _rows(
            conn,
            "SELECT * FROM remotes WHERE enabled=1 AND status!='full' ORDER BY priority, id LIMIT ?",
            (count,),
        )


def get_active_remote(db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    remotes = get_active_remotes(1, db_path)
    return remotes[0] if remotes else None


def add_remote(data: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO remotes
               (name,provider,base_remote,crypt_remote,secrets_crypt_remote,
                priority,enabled,authorized_email,notes)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                data["name"], data.get("provider", "drive"),
                data["base_remote"], data["crypt_remote"],
                data.get("secrets_crypt_remote"),
                data.get("priority", 1), 1,
                data.get("authorized_email"),
                data.get("notes"),
            ),
        )
    return cur.lastrowid


def update_remote(remote_id: int, fields: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    allowed = {
        "name", "priority", "enabled", "status", "capacity_total_gb", "capacity_used_gb",
        "capacity_checked_at", "fill_threshold_percent", "authorized_email",
        "account_display_name", "account_photo_url", "authorized_at", "notes",
        "secrets_crypt_remote",
    }
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    set_clause = ", ".join(f"{k}=?" for k in safe)
    with get_conn(db_path) as conn:
        conn.execute(
            f"UPDATE remotes SET {set_clause} WHERE id=?",
            (*safe.values(), remote_id),
        )


def delete_remote(remote_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM remotes WHERE id=?", (remote_id,))


def rotate_to_next_remote(current_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    """Mark current remote as full, return the next viable remote."""
    update_remote(current_id, {"status": "full"}, db_path)
    with get_conn(db_path) as conn:
        nxt = _row(
            conn,
            "SELECT * FROM remotes WHERE enabled=1 AND status!='full' AND id!=? ORDER BY priority,id LIMIT 1",
            (current_id,),
        )
    return nxt


def reorder_remotes(ordered_ids: list[int], db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        for priority, rid in enumerate(ordered_ids, start=1):
            conn.execute("UPDATE remotes SET priority=? WHERE id=?", (priority, rid))


# ─── sources ──────────────────────────────────────────────────────────────────

def get_sources(host: str = "supermicro.local", db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, "SELECT * FROM sources WHERE host=? ORDER BY data_class, priority, id", (host,))


def add_source(data: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO sources(host,name,path,data_class,priority,enabled,
               include_patterns,exclude_patterns,notes)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                data.get("host", "supermicro.local"), data["name"], data["path"],

                data.get("data_class", "config"), data.get("priority", 2),
                1,
                json.dumps(data.get("include_patterns", ["*"])),
                json.dumps(data.get("exclude_patterns", ["*.tmp", "*.bak", "*.swp"])),
                data.get("notes"),
            ),
        )
    return cur.lastrowid


def toggle_source(source_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("UPDATE sources SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (source_id,))


def delete_source(source_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM sources WHERE id=?", (source_id,))


# ─── jobs ─────────────────────────────────────────────────────────────────────

def get_jobs(host: str = "supermicro.local", db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, "SELECT j.*, r.name AS remote_name FROM jobs j LEFT JOIN remotes r ON r.id=j.remote_id WHERE j.host=? ORDER BY j.id", (host,))


def get_job(job_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        return _row(conn, "SELECT j.*, r.name AS remote_name, r.crypt_remote FROM jobs j LEFT JOIN remotes r ON r.id=j.remote_id WHERE j.id=?", (job_id,))


def add_job(data: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO jobs(name,host,data_class,remote_id,mode,schedule_cron,
               target_count,enabled,extra_flags,pre_hook,notify_on_failure,notify_on_success,notes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                data["name"], data.get("host", "supermicro.local"), data["data_class"],

                data.get("remote_id"), data.get("mode", "copy"),
                data.get("schedule_cron"), int(data.get("target_count", 2)), 1,
                json.dumps(data.get("extra_flags", [])),
                data.get("pre_hook"),
                int(data.get("notify_on_failure", 1)),
                int(data.get("notify_on_success", 0)),
                data.get("notes"),
            ),
        )
    return cur.lastrowid


def update_job(job_id: int, fields: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    allowed = {"name", "remote_id", "mode", "schedule_cron", "target_count", "enabled",
               "extra_flags", "pre_hook", "notify_on_failure", "notify_on_success", "notes"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    safe["updated_at"] = _now()
    set_clause = ", ".join(f"{k}=?" for k in safe)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE jobs SET {set_clause} WHERE id=?", (*safe.values(), job_id))


def delete_job(job_id: int, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))


def toggle_job(job_id: int, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET enabled = CASE WHEN enabled=1 THEN 0 ELSE 1 END, updated_at=? WHERE id=?",
            (_now(), job_id),
        )
        row = _row(conn, "SELECT enabled FROM jobs WHERE id=?", (job_id,))
    return row["enabled"] if row else 0


# ─── runs & run_targets ───────────────────────────────────────────────────────

def create_run(job_id: int, remote_id: Optional[int] = None, triggered_by: str = "manual",
               rclone_command: str = "", log_path: str = "",
               db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO runs(job_id,remote_id,triggered_by,started_at,status,rclone_command,log_path)
               VALUES(?,?,?,?,?,?,?)""",
            (job_id, remote_id, triggered_by, _now(), "running", rclone_command, log_path),
        )
    return cur.lastrowid


def finish_run(run_id: int, status: str, exit_code: int, bytes_transferred: int = 0,
               files_transferred: int = 0, files_checked: int = 0, errors: int = 0,
               db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DROP TRIGGER IF EXISTS runs_no_update")
        conn.execute(
            """UPDATE runs SET finished_at=?, status=?, exit_code=?,
               bytes_transferred=?, files_transferred=?, files_checked=?, errors=?
               WHERE id=?""",
            (_now(), status, exit_code, bytes_transferred, files_transferred,
             files_checked, errors, run_id),
        )
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS runs_no_update
                BEFORE UPDATE ON runs
                BEGIN SELECT RAISE(ABORT, 'runs table is append-only: UPDATE not permitted'); END
        """)
        conn.commit()


def create_run_target(run_id: int, remote_id: int, target_role: str = "primary",
                      rclone_command: str = "", log_path: str = "",
                      db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO run_targets(run_id,remote_id,role,started_at,status,rclone_command,log_path)
               VALUES(?,?,?,?,?,?,?)""",
            (run_id, remote_id, target_role, _now(), "running", rclone_command, log_path),
        )
    return cur.lastrowid



def finish_run_target(run_target_id: int, status: str, exit_code: int,
                      bytes_transferred: int = 0, files_transferred: int = 0,
                      files_checked: int = 0, errors: int = 0,
                      db_path: str = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DROP TRIGGER IF EXISTS run_targets_no_update")
        conn.commit()
        conn.execute(
            """UPDATE run_targets SET finished_at=?, status=?, exit_code=?,
               bytes_transferred=?, files_transferred=?, files_checked=?, errors=?
               WHERE id=?""",
            (_now(), status, exit_code, bytes_transferred, files_transferred,
             files_checked, errors, run_target_id),
        )
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS run_targets_no_update
                BEFORE UPDATE ON run_targets
                BEGIN SELECT RAISE(ABORT, 'run_targets table is append-only: UPDATE not permitted'); END
        """)
        conn.commit()



def get_run_targets(run_id: int, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, """
            SELECT rt.*, rm.name AS remote_name, rm.crypt_remote
            FROM run_targets rt
            JOIN remotes rm ON rm.id = rt.remote_id
            WHERE rt.run_id = ?
            ORDER BY rt.id
        """, (run_id,))


def get_successful_restore_targets(run_id: int, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    """Return ONLY target streams that completed with status = 'success' for restore selection."""
    with get_conn(db_path) as conn:
        return _rows(conn, """
            SELECT rt.*, rm.name AS remote_name, rm.crypt_remote
            FROM run_targets rt
            JOIN remotes rm ON rm.id = rt.remote_id
            WHERE rt.run_id = ? AND rt.status = 'success'
            ORDER BY rt.id
        """, (run_id,))


def get_runs(job_id: Optional[int] = None, limit: int = 50, offset: int = 0,
             status: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    clauses = []
    params: list[Any] = []
    if job_id is not None:
        clauses.append("r.job_id=?")
        params.append(job_id)
    if status:
        clauses.append("r.status=?")
        params.append(status)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params += [limit, offset]
    with get_conn(db_path) as conn:
        runs = _rows(conn, f"""
            SELECT r.*, j.name AS job_name, j.data_class, rm.name AS remote_name
            FROM runs r
            JOIN jobs j ON j.id=r.job_id
            LEFT JOIN remotes rm ON rm.id=r.remote_id
            {where}
            ORDER BY r.started_at DESC
            LIMIT ? OFFSET ?
        """, tuple(params))
        for run in runs:
            run["targets"] = _rows(conn, """
                SELECT rt.*, rm.name AS remote_name
                FROM run_targets rt
                JOIN remotes rm ON rm.id=rt.remote_id
                WHERE rt.run_id=?
            """, (run["id"],))
        return runs


def get_run(run_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        run = _row(conn, """
            SELECT r.*, j.name AS job_name, j.data_class, j.host,
                   rm.name AS remote_name, rm.crypt_remote
            FROM runs r
            JOIN jobs j ON j.id=r.job_id
            LEFT JOIN remotes rm ON rm.id=r.remote_id
            WHERE r.id=?
        """, (run_id,))
        if run:
            run["targets"] = get_run_targets(run_id, db_path)
        return run


def get_recent_runs(limit: int = 20, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    return get_runs(limit=limit, db_path=db_path)


# ─── restores ─────────────────────────────────────────────────────────────────

def create_restore(data: dict, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO restores(source_run_id,remote_id,data_class,remote_path,
               dest_path,dest_is_production,operator)
               VALUES(?,?,?,?,?,?,?)""",
            (
                data.get("source_run_id"), data["remote_id"], data["data_class"],
                data["remote_path"], data["dest_path"],
                int(data.get("dest_is_production", 0)),
                data.get("operator", "admin"),
            ),
        )
    return cur.lastrowid


def update_restore(restore_id: int, fields: dict, db_path: str = DEFAULT_DB_PATH) -> None:
    allowed = {"dry_run_done", "confirmed", "status", "started_at", "finished_at",
               "files_restored", "log_path", "rclone_command"}
    safe = {k: v for k, v in fields.items() if k in allowed}
    if not safe:
        return
    set_clause = ", ".join(f"{k}=?" for k in safe)
    with get_conn(db_path) as conn:
        conn.execute(f"UPDATE restores SET {set_clause} WHERE id=?", (*safe.values(), restore_id))


def get_restores(limit: int = 30, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, """
            SELECT rs.*, rm.name AS remote_name
            FROM restores rs
            JOIN remotes rm ON rm.id=rs.remote_id
            ORDER BY rs.created_at DESC LIMIT ?
        """, (limit,))


def get_restore(restore_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        return _row(conn, """
            SELECT rs.*, rm.name AS remote_name
            FROM restores rs
            JOIN remotes rm ON rm.id=rs.remote_id
            WHERE rs.id=?
        """, (restore_id,))


# ─── audit_log ────────────────────────────────────────────────────────────────

def audit(actor: str, action: str, target_type: str = "", target_id: Optional[int] = None,
          detail: Any = None, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_log(actor,action,target_type,target_id,detail) VALUES(?,?,?,?,?)\n",
            (actor, action, target_type, target_id, json.dumps(detail) if detail else None),
        )


def get_audit_log(limit: int = 100, db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, "SELECT * FROM audit_log ORDER BY ts DESC LIMIT ?", (limit,))


# ─── Dashboard aggregation ────────────────────────────────────────────────────

def get_dashboard_data(db_path: str = DEFAULT_DB_PATH, rclone_conf: Optional[str] = None) -> dict:
    if not rclone_conf:
        rclone_conf = os.environ.get("RCLONE_CONF", r"C:\ProgramData\CloudBackup\rclone.conf")


    from shared.google_account import fetch_google_account_info

    with get_conn(db_path) as conn:
        remotes = _rows(conn, "SELECT * FROM remotes ORDER BY priority, id")
        recent_runs = get_runs(limit=10, db_path=db_path)
        jobs = _rows(conn, "SELECT * FROM jobs ORDER BY id")
        system_state = _row(conn, "SELECT value FROM system_state WHERE key='state'")
        active_remote_id = _row(conn, "SELECT value FROM system_state WHERE key='active_remote_id'")
        failures_24h = _row(conn, """
            SELECT COUNT(*) AS cnt FROM runs
            WHERE status='failed'
            AND started_at >= datetime('now','-1 day')
        """)

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

    return {
        "remotes": enriched_remotes,
        "recent_runs": recent_runs,
        "jobs": jobs,
        "system_state": system_state["value"] if system_state else "ACTIVE",
        "active_remote_id": active_remote_id["value"] if active_remote_id else None,
        "failures_24h": failures_24h["cnt"] if failures_24h else 0,
    }




# ─── users ────────────────────────────────────────────────────────────────────

def get_users(db_path: str = DEFAULT_DB_PATH) -> list[dict]:
    with get_conn(db_path) as conn:
        return _rows(conn, "SELECT id, username, role, totp_secret, created_at, updated_at FROM users ORDER BY id")


def get_user_by_username(username: str, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        return _row(conn, "SELECT * FROM users WHERE username=?", (username.strip().lower(),))


def get_user_by_id(user_id: int, db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    with get_conn(db_path) as conn:
        return _row(conn, "SELECT * FROM users WHERE id=?", (user_id,))


def add_user(username: str, password_hash: str, role: str = "admin",
             totp_secret: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> int:
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO users(username, password_hash, role, totp_secret, created_at)
               VALUES(?,?,?,?,?)""",
            (username.strip().lower(), password_hash, role, totp_secret, _now()),
        )
    return cur.lastrowid


def update_user_password(user_id: int, new_password_hash: str, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (new_password_hash, _now(), user_id),
        )


def update_user_totp(user_id: int, totp_secret: str, db_path: str = DEFAULT_DB_PATH) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "UPDATE users SET totp_secret=?, updated_at=? WHERE id=?",
            (totp_secret, _now(), user_id),
        )


def delete_user(user_id: int, db_path: str = DEFAULT_DB_PATH) -> bool:
    with get_conn(db_path) as conn:
        count = _row(conn, "SELECT COUNT(*) as cnt FROM users")["cnt"]
        if count <= 1:
            raise ValueError("Cannot delete the last remaining user account")
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    return True

