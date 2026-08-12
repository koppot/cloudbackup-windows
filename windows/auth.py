import hashlib
import json
import os
import secrets

def hash_password(password: str) -> str:
    """Hashes a password with a static salt for simplicity, or generates a fresh one in a real app."""
    # Simplified version for single password setup
    salt = "adc_backup_windows_salt"
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

def check_password(password: str, auth_json_path: str) -> bool:
    """Check if the provided password matches the stored one."""
    if not os.path.exists(auth_json_path):
        return False
    try:
        with open(auth_json_path, 'r') as f:
            data = json.load(f)
        stored_hash = data.get('password_hash')
        if not stored_hash:
            return False
        return hash_password(password) == stored_hash
    except Exception:
        return False

def is_authenticated(cookies: dict, session_file_path: str) -> bool:
    """Check if the session cookie is valid."""
    session_token = cookies.get('session_id')
    if not session_token:
        return False
    if not os.path.exists(session_file_path):
        return False
    try:
        with open(session_file_path, 'r') as f:
            data = json.load(f)
        return data.get('session_id') == session_token
    except Exception:
        return False

def create_session(session_file_path: str) -> str:
    """Create a new session and save to file."""
    session_token = secrets.token_urlsafe(32)
    os.makedirs(os.path.dirname(session_file_path), exist_ok=True)
    with open(session_file_path, 'w') as f:
        json.dump({'session_id': session_token}, f)
    return session_token

def clear_session(session_file_path: str):
    """Clear the active session."""
    if os.path.exists(session_file_path):
        os.remove(session_file_path)
