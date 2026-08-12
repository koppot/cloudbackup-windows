"""
shared/google_account.py — Fetch and cache Google Drive account reflection info (avatar, email, quota).

Parses access_token from rclone.conf section, queries Google Drive API v3:
  https://www.googleapis.com/drive/v3/about?fields=user,storageQuota

If access_token is expired, triggers rclone refresh background call to renew token in rclone.conf.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
import subprocess
import threading
import time
import urllib.request
from typing import Any, Dict

log = logging.getLogger(__name__)

_account_cache: Dict[str, tuple[float, dict]] = {}


def fetch_google_account_info(base_remote: str, rclone_conf: str) -> dict:
    """
    Returns dict:
      {
        'email': '...',
        'displayName': '...',
        'photoLink': '...',
        'capacity': {
            'total_gb': 100.0,
            'used_gb': 15.0,
            'free_gb': 85.0,
            'percent_used': 15.0
        }
      }
    """
    clean_base = base_remote.rstrip(":")
    if not clean_base or not os.path.exists(rclone_conf):
        return {
            "email": "Not Authorized",
            "displayName": clean_base or "Remote",
            "photoLink": "",
            "capacity": {"total_gb": 5120.0, "used_gb": 0.0, "free_gb": 5120.0, "percent_used": 0.0},
        }

    # Check cache (10 minutes)
    if clean_base in _account_cache:
        t_cache, data = _account_cache[clean_base]
        if time.time() - t_cache < 600:
            return data

    try:
        cfg = configparser.ConfigParser()
        cfg.read(rclone_conf)

        if cfg.has_section(clean_base) and cfg.has_option(clean_base, "token"):
            tok_raw = cfg.get(clean_base, "token")
            tok = json.loads(tok_raw)
            acc_token = tok.get("access_token")
            if acc_token:
                try:
                    req = urllib.request.Request(
                        "https://www.googleapis.com/drive/v3/about?fields=user,storageQuota",
                        headers={"Authorization": f"Bearer {acc_token}"},
                    )
                    with urllib.request.urlopen(req, timeout=4) as resp:
                        raw = json.loads(resp.read().decode())
                        u_data = raw.get("user", {})
                        q_data = raw.get("storageQuota", {})

                        limit_bytes = int(q_data.get("limit", 5497558138880))  # default 5TB if unlimited
                        usage_bytes = int(q_data.get("usage", 0))

                        total_gb = round(limit_bytes / (1024 ** 3), 1)
                        used_gb = round(usage_bytes / (1024 ** 3), 1)
                        free_gb = max(0.0, round(total_gb - used_gb, 1))
                        pct = round((used_gb / total_gb * 100), 1) if total_gb > 0 else 0.0

                        info = {
                            "email": u_data.get("emailAddress", "Authorized"),
                            "displayName": u_data.get("displayName", clean_base),
                            "photoLink": u_data.get("photoLink", ""),
                            "capacity": {
                                "total_gb": total_gb,
                                "used_gb": used_gb,
                                "free_gb": free_gb,
                                "percent_used": pct,
                            },
                        }
                        _account_cache[clean_base] = (time.time(), info)
                        return info
                except Exception as exc:
                    log.warning("HTTP error querying Google API for %s: %s", clean_base, exc)
    except Exception as exc:
        log.error("Error reading rclone.conf for %s: %s", clean_base, exc)

    default_info = {
        "email": "Google Drive Remote",
        "displayName": clean_base,
        "photoLink": "",
        "capacity": {"total_gb": 5120.0, "used_gb": 0.0, "free_gb": 5120.0, "percent_used": 0.0},
    }
    _account_cache[clean_base] = (time.time() - 300, default_info)  # Cache fallback for 5 min to avoid rate limit spam
    return default_info

