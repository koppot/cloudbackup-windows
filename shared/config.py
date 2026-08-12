"""
shared/config.py — CloudBackup for Windows configuration loader.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    import yaml
except ImportError:
    raise RuntimeError(
        "PyYAML is required. Install with: pip install pyyaml"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sub-configs
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DatabaseConfig:
    db_path: str = r"C:\ProgramData\CloudBackup\state.db"
    backup_dir: str = r"C:\ProgramData\CloudBackup\catalog_backups"
    state_path: str = r"C:\ProgramData\CloudBackup\state.json"


    @classmethod
    def from_dict(cls, d: dict) -> "DatabaseConfig":
        return cls(
            db_path=d.get("db_path", cls.__dataclass_fields__["db_path"].default),
            backup_dir=d.get("backup_dir", cls.__dataclass_fields__["backup_dir"].default),
            state_path=d.get("state_path", cls.__dataclass_fields__["state_path"].default),
        )


@dataclass
class DriveRemoteConfig:
    """One Google Drive account — base + data crypt + optional secrets crypt."""
    name: str                          # e.g. "gdrive1_crypt"
    base_remote: str                   # e.g. "gdrive1:"
    crypt_remote: str                  # e.g. "gdrive1_crypt:"
    priority: int = 1
    enabled: bool = True
    data_subdir: str = "backup"
    secrets_crypt_remote: Optional[str] = None   # e.g. "gdrive1_secrets_crypt:"
    secrets_subdir: str = "secrets"

    @classmethod
    def from_dict(cls, d: dict) -> "DriveRemoteConfig":
        name = d["name"]
        base = d["base_remote"].rstrip(":") + ":"
        crypt = d.get("crypt_remote", name + ":").rstrip(":") + ":"
        return cls(
            name=name,
            base_remote=base,
            crypt_remote=crypt,
            priority=int(d.get("priority", 1)),
            enabled=bool(d.get("enabled", True)),
            data_subdir=d.get("data_subdir", "backup"),
            secrets_crypt_remote=(
                d["secrets_crypt_remote"].rstrip(":") + ":"
                if d.get("secrets_crypt_remote") else None
            ),
            secrets_subdir=d.get("secrets_subdir", "secrets"),
        )


@dataclass
class DrivesConfig:
    remotes: List[DriveRemoteConfig] = field(default_factory=list)
    reserve_margin_percent: float = 5.0
    reserve_margin_bytes: int = 10 * 1024 ** 3   # 10 GB

    @classmethod
    def from_dict(cls, d: dict) -> "DrivesConfig":
        remotes = [DriveRemoteConfig.from_dict(r) for r in d.get("remotes", [])]
        return cls(
            remotes=remotes,
            reserve_margin_percent=float(d.get("reserve_margin_percent", 5.0)),
            reserve_margin_bytes=int(d.get("reserve_margin_bytes", 10 * 1024 ** 3)),
        )

    def get_remote(self, name: str) -> Optional[DriveRemoteConfig]:
        for r in self.remotes:
            if r.name == name:
                return r
        return None

    def enabled_by_priority(self) -> List[DriveRemoteConfig]:
        """Return enabled remotes sorted by priority ascending (1 = highest)."""
        return sorted(
            [r for r in self.remotes if r.enabled],
            key=lambda r: r.priority,
        )


@dataclass
class SourceConfig:
    name: str
    path: str
    priority: int = 1
    enabled: bool = True
    include_patterns: List[str] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "SourceConfig":
        return cls(
            name=d["name"],
            path=d["path"],
            priority=int(d.get("priority", 1)),
            enabled=bool(d.get("enabled", True)),
            include_patterns=d.get("include_patterns", []),
            exclude_patterns=d.get("exclude_patterns", []),
        )


@dataclass
class HostConfig:
    name: str
    enabled: bool = True
    sources: List[SourceConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "HostConfig":
        return cls(
            name=d["name"],
            enabled=bool(d.get("enabled", True)),
            sources=[SourceConfig.from_dict(s) for s in d.get("sources", [])],
        )

    def enabled_sources_by_priority(self) -> List[SourceConfig]:
        return sorted(
            [s for s in self.sources if s.enabled],
            key=lambda s: s.priority,
        )


@dataclass
class RcloneConfig:
    """rclone transfer tuning parameters."""
    bin: str = "rclone"
    tpslimit: int = 10
    tpslimit_burst: int = 10
    transfers: int = 4
    checkers: int = 8
    drive_chunk_size: str = "64M"
    fast_list: bool = True
    retries: int = 5
    low_level_retries: int = 10
    stats_interval: str = "30s"

    @classmethod
    def from_dict(cls, d: dict) -> "RcloneConfig":
        return cls(
            bin=d.get("bin", "rclone"),
            tpslimit=int(d.get("tpslimit", 10)),
            tpslimit_burst=int(d.get("tpslimit_burst", 10)),
            transfers=int(d.get("transfers", 4)),
            checkers=int(d.get("checkers", 8)),
            drive_chunk_size=d.get("drive_chunk_size", "64M"),
            fast_list=bool(d.get("fast_list", True)),
            retries=int(d.get("retries", 5)),
            low_level_retries=int(d.get("low_level_retries", 10)),
            stats_interval=d.get("stats_interval", "30s"),
        )

    def base_flags(self) -> List[str]:
        """Return the list of rclone flags derived from this config."""
        flags = [
            "--tpslimit", str(self.tpslimit),
            "--tpslimit-burst", str(self.tpslimit_burst),
            "--transfers", str(self.transfers),
            "--checkers", str(self.checkers),
            "--drive-chunk-size", self.drive_chunk_size,
            "--retries", str(self.retries),
            "--low-level-retries", str(self.low_level_retries),
            "--stats", self.stats_interval,
        ]
        if self.fast_list:
            flags.append("--fast-list")
        return flags


@dataclass
class RestoreTestingConfig:
    staging_dir: str = r"C:\ProgramData\CloudBackup\temp"

    auto_cleanup: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "RestoreTestingConfig":
        return cls(
            staging_dir=d.get("staging_dir", cls.__dataclass_fields__["staging_dir"].default),
            auto_cleanup=bool(d.get("auto_cleanup", True)),
        )


@dataclass
class SecretsConfig:
    """References the secrets_class.yaml path; does NOT hold any secret values."""
    class_file: str = r"C:\ProgramData\CloudBackup\secrets_class.yaml"
    key_hint: str = "See password manager: secrets"

    @classmethod
    def from_dict(cls, d: dict) -> "SecretsConfig":
        return cls(
            class_file=d.get("class_file", cls.__dataclass_fields__["class_file"].default),
            key_hint=d.get("key_hint", cls.__dataclass_fields__["key_hint"].default),
        )


@dataclass
class ServerConfig:
    """UI server settings."""
    host: str = "127.0.0.1"
    port: int = 8765
    tailscale_only: bool = False
    debug: bool = False
    log_dir: str = r"C:\ProgramData\CloudBackup\logs"

    @classmethod
    def from_dict(cls, d: dict) -> "ServerConfig":
        return cls(
            host=d.get("host", "127.0.0.1"),
            port=int(d.get("port", 8765)),
            tailscale_only=bool(d.get("tailscale_only", False)),
            debug=bool(d.get("debug", False)),
            log_dir=d.get("log_dir", cls.__dataclass_fields__["log_dir"].default),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Root config
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AppConfig:
    rclone_conf: str           # Absolute path to rclone.conf
    database: DatabaseConfig
    drives: DrivesConfig
    hosts: List[HostConfig]
    rclone: RcloneConfig
    secrets: SecretsConfig
    server: ServerConfig
    restore_testing: RestoreTestingConfig
    hostname: str = "supermicro.local"    # Used as top-level subdir on Drive: hostname/classname/


    @classmethod
    def load(cls, path: str) -> "AppConfig":
        """Load and validate config from a YAML file."""
        config_path = Path(path).expanduser().resolve()
        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {config_path}\n"
                f"Create configuration at {config_path} and edit it."
            )

        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)

        if not isinstance(raw, dict):
            raise ValueError(f"Config file is empty or invalid YAML: {config_path}")

        rclone_conf = raw.get("rclone_conf", r"C:\ProgramData\CloudBackup\rclone.conf")


        return cls(
            rclone_conf=str(Path(rclone_conf).expanduser()),
            database=DatabaseConfig.from_dict(raw.get("database", {})),
            drives=DrivesConfig.from_dict(raw.get("drives", {})),
            hosts=[HostConfig.from_dict(h) for h in raw.get("hosts", [])],
            rclone=RcloneConfig.from_dict(raw.get("rclone", {})),
            secrets=SecretsConfig.from_dict(raw.get("secrets", {})),
            server=ServerConfig.from_dict(raw.get("server", {})),
            restore_testing=RestoreTestingConfig.from_dict(
                raw.get("restore_testing", {})
            ),
            hostname=raw.get("hostname", cls.__dataclass_fields__["hostname"].default),
        )

    def validate(self) -> List[str]:
        """
        Return a list of validation warnings.
        Empty list = all checks passed.
        """
        warnings: List[str] = []

        if not Path(self.rclone_conf).exists():
            warnings.append(
                f"rclone.conf not found at {self.rclone_conf}. "
                "Run 'rclone config' to create it."
            )

        if not self.drives.remotes:
            warnings.append(
                "No drive remotes configured. Add at least one remote under drives.remotes."
            )

        enabled = self.drives.enabled_by_priority()
        if not enabled:
            warnings.append("No drives are enabled. Set enabled: true on at least one remote.")

        secrets_file = Path(self.secrets.class_file)
        if not secrets_file.exists():
            warnings.append(
                f"secrets_class.yaml not found at {self.secrets.class_file}. "
                "Copy secrets_class.yaml.example and edit it."
            )

        log_dir = Path(self.server.log_dir)
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                warnings.append(f"Cannot create log directory {log_dir}: {e}")

        return warnings
