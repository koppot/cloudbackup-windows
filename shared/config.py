"""
shared/config.py — CloudBackup for Windows configuration loader with central path integration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .paths import (
    get_config_dir,
    get_default_db_path,
    get_default_rclone_conf_path,
    get_log_dir,
    get_programdata_dir,
    get_state_dir,
    get_temp_dir,
    validate_local_path,
)

try:
    import yaml
except ImportError:
    raise RuntimeError("PyYAML is required. Install with: pip install pyyaml")


@dataclass
class DatabaseConfig:
    db_path: str = ""
    backup_dir: str = ""
    state_path: str = ""

    def __post_init__(self):
        if not self.db_path:
            self.db_path = str(get_default_db_path())
        if not self.backup_dir:
            self.backup_dir = str(get_state_dir() / "catalog_backups")
        if not self.state_path:
            self.state_path = str(get_state_dir() / "state.json")

    @classmethod
    def from_dict(cls, d: dict) -> "DatabaseConfig":
        return cls(
            db_path=d.get("db_path", str(get_default_db_path())),
            backup_dir=d.get("backup_dir", str(get_state_dir() / "catalog_backups")),
            state_path=d.get("state_path", str(get_state_dir() / "state.json")),
        )


@dataclass
class DriveRemoteConfig:
    name: str
    base_remote: str
    crypt_remote: str
    priority: int = 1
    enabled: bool = True
    data_subdir: str = "backup"
    secrets_crypt_remote: Optional[str] = None
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
    reserve_margin_bytes: int = 10 * 1024 ** 3

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
    staging_dir: str = ""
    auto_cleanup: bool = True

    def __post_init__(self):
        if not self.staging_dir:
            self.staging_dir = str(get_temp_dir() / "restore_test")

    @classmethod
    def from_dict(cls, d: dict) -> "RestoreTestingConfig":
        return cls(
            staging_dir=d.get("staging_dir", str(get_temp_dir() / "restore_test")),
            auto_cleanup=bool(d.get("auto_cleanup", True)),
        )


@dataclass
class SecretsConfig:
    class_file: str = ""
    key_hint: str = "See password manager: secrets"

    def __post_init__(self):
        if not self.class_file:
            self.class_file = str(get_config_dir() / "secrets_class.yaml")

    @classmethod
    def from_dict(cls, d: dict) -> "SecretsConfig":
        return cls(
            class_file=d.get("class_file", str(get_config_dir() / "secrets_class.yaml")),
            key_hint=d.get("key_hint", "See password manager: secrets"),
        )


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    tailscale_only: bool = False
    debug: bool = False
    log_dir: str = ""

    def __post_init__(self):
        if not self.log_dir:
            self.log_dir = str(get_log_dir())

    @classmethod
    def from_dict(cls, d: dict) -> "ServerConfig":
        return cls(
            host=d.get("host", "127.0.0.1"),
            port=int(d.get("port", 8765)),
            tailscale_only=bool(d.get("tailscale_only", False)),
            debug=bool(d.get("debug", False)),
            log_dir=d.get("log_dir", str(get_log_dir())),
        )


@dataclass
class AppConfig:
    rclone_conf: str
    database: DatabaseConfig
    drives: DrivesConfig
    hosts: List[HostConfig]
    rclone: RcloneConfig
    secrets: SecretsConfig
    server: ServerConfig
    restore_testing: RestoreTestingConfig
    hostname: str = "supermicro.local"

    @classmethod
    def load(cls, path: str) -> "AppConfig":
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

        rclone_conf = raw.get("rclone_conf", str(get_default_rclone_conf_path()))

        return cls(
            rclone_conf=str(Path(rclone_conf).expanduser()),
            database=DatabaseConfig.from_dict(raw.get("database", {})),
            drives=DrivesConfig.from_dict(raw.get("drives", {})),
            hosts=[HostConfig.from_dict(h) for h in raw.get("hosts", [])],
            rclone=RcloneConfig.from_dict(raw.get("rclone", {})),
            secrets=SecretsConfig.from_dict(raw.get("secrets", {})),
            server=ServerConfig.from_dict(raw.get("server", {})),
            restore_testing=RestoreTestingConfig.from_dict(raw.get("restore_testing", {})),
            hostname=raw.get("hostname", "supermicro.local"),
        )

    def validate(self) -> List[str]:
        warnings: List[str] = []

        if not Path(self.rclone_conf).exists():
            warnings.append(
                f"rclone.conf not found at {self.rclone_conf}. "
                "Run setup wizard to generate configuration."
            )

        if not self.drives.remotes:
            warnings.append("No drive remotes configured.")

        enabled = self.drives.enabled_by_priority()
        if not enabled:
            warnings.append("No drives are enabled.")

        log_dir = Path(self.server.log_dir)
        if not log_dir.exists():
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                warnings.append(f"Cannot create log directory {log_dir}: {e}")

        return warnings
