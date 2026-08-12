import json
import os
import bcrypt
import pyotp
from functools import wraps
from flask import session, redirect, url_for, flash

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def generate_totp_secret() -> str:
    return pyotp.random_base32()

def get_totp_uri(secret: str, issuer: str = 'ADC Backup', account: str = 'admin') -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)

def verify_totp(secret: str, token: str) -> bool:
    totp = pyotp.TOTP(secret)
    return totp.verify(token, valid_window=1)

def is_authenticated(session_obj) -> bool:
    return session_obj.get('authenticated', False) is True

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated(session):
            return redirect(url_for('auth_bp.login'))
        return f(*args, **kwargs)
    return decorated_function
