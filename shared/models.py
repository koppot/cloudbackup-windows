from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
import json

class DataClass(str, Enum):
    CONFIG = 'config'
    DATA = 'data'
    SECRETS = 'secrets'
    PACKAGES = 'packages'

class JobMode(str, Enum):
    COPY = 'copy'
    SYNC = 'sync'

class RunStatus(str, Enum):
    RUNNING = 'running'
    SUCCESS = 'success'
    PARTIAL = 'partial'
    FAILED = 'failed'
    ABORTED = 'aborted'

class RemoteStatus(str, Enum):
    UNKNOWN = 'unknown'
    OK = 'ok'
    FULL = 'full'
    UNAUTHORIZED = 'unauthorized'
    ERROR = 'error'
    DISABLED = 'disabled'

@dataclass
class Remote:
    id: int
    name: str
    provider: str
    base_remote: str
    crypt_remote: str
    data_subdir: str
    secrets_crypt_remote: str
    secrets_subdir: str
    priority: int
    enabled: bool
    status: str
    capacity_total_gb: Optional[float]
    capacity_used_gb: Optional[float]
    capacity_free_gb: Optional[float]
    capacity_pct_used: Optional[float]
    capacity_checked_at: Optional[str]
    authorized_email: Optional[str]
    authorized_at: Optional[str]
    notes: Optional[str]
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> 'Remote':
        return cls(**{k: v for k, v in row.items() if k in cls.__annotations__})

@dataclass
class Job:
    id: int
    name: str
    host: str
    data_class: str
    source_paths: List[str]
    remote_id: Optional[int]
    mode: str
    schedule_cron: Optional[str]
    enabled: bool
    pre_hook: Optional[str]
    rclone_extra_flags: List[str]
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: dict) -> 'Job':
        d = dict(row)
        if isinstance(d.get('source_paths'), str):
            try:
                d['source_paths'] = json.loads(d['source_paths'])
            except:
                d['source_paths'] = []
        if isinstance(d.get('rclone_extra_flags'), str):
            try:
                d['rclone_extra_flags'] = json.loads(d['rclone_extra_flags'])
            except:
                d['rclone_extra_flags'] = []
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

@dataclass
class Run:
    id: int
    job_id: int
    remote_id: int
    started_at: str
    finished_at: Optional[str]
    status: str
    exit_code: Optional[int]
    bytes_transferred: Optional[int]
    files_transferred: Optional[int]
    files_checked: Optional[int]
    errors: Optional[int]
    rclone_command: str
    log_path: Optional[str]
    rotated_from_remote_id: Optional[int]
    triggered_by: str
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> 'Run':
        return cls(**{k: v for k, v in row.items() if k in cls.__annotations__})
        
    @property
    def status_badge(self) -> str:
        mapping = {
            'running': 'badge-primary',
            'success': 'badge-success',
            'partial': 'badge-warning',
            'failed': 'badge-danger',
            'aborted': 'badge-secondary'
        }
        return mapping.get(self.status.lower(), 'badge-light')

@dataclass
class Restore:
    id: int
    run_id: Optional[int]
    remote_id: int
    data_class: str
    source_path: str
    dest_path: str
    dry_run: bool
    started_at: str
    finished_at: Optional[str]
    status: str
    files_restored: Optional[int]
    bytes_restored: Optional[int]
    log_path: Optional[str]
    operator: str
    notes: Optional[str]
    created_at: str

    @classmethod
    def from_row(cls, row: dict) -> 'Restore':
        d = dict(row)
        d['dry_run'] = bool(d.get('dry_run'))
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

@dataclass
class RotationEvent:
    id: int
    run_id: Optional[int]
    from_remote_id: Optional[int]
    to_remote_id: int
    reason: str
    triggered_at: str
    notes: Optional[str]

    @classmethod
    def from_row(cls, row: dict) -> 'RotationEvent':
        return cls(**{k: v for k, v in row.items() if k in cls.__annotations__})
