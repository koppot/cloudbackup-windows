import hashlib
import json
import os
import secrets


def hash_password(password: str) -> str:
    """Hash a password with a static salt."""
    salt = "cloud_backup_windows_salt"
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def is_first_run(auth_json_path: str) -> bool:
    """Return True when no password has been configured (first-run state)."""
    return not os.path.exists(auth_json_path)


def check_password(password: str, auth_json_path: str) -> bool:
    """Return True if the provided password matches the stored hash."""
    if not os.path.exists(auth_json_path):
        return False
    try:
        with open(auth_json_path, "r") as f:
            data = json.load(f)
        stored_hash = data.get("password_hash")
        if not stored_hash:
            return False
        return hash_password(password) == stored_hash
    except Exception:
        return False


def is_authenticated(cookies: dict, session_file_path: str) -> bool:
    """Return True when the 'session' cookie matches the stored session token."""
    # Cookie name is 'session' (set by create_session via Set-Cookie header).
    session_token = cookies.get("session")
    if not session_token:
        return False
    if not os.path.exists(session_file_path):
        return False
    try:
        with open(session_file_path, "r") as f:
            data = json.load(f)
        return data.get("session_id") == session_token
    except Exception:
        return False


def create_session(session_file_path: str) -> str:
    """Create a new session token, persist it, and return the token."""
    session_token = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(session_file_path), exist_ok=True)
    with open(session_file_path, "w") as f:
        json.dump({"session_id": session_token}, f)
    return session_token


def clear_session(session_file_path: str) -> None:
    """Invalidate the current session."""
    if os.path.exists(session_file_path):
        os.remove(session_file_path)

