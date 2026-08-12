-- ADC Backup System — SQLite Schema
-- Version: 1.0
-- Engine: SQLite 3 (WAL mode enabled at runtime)
-- All timestamps are ISO-8601 UTC strings.

PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ─── remotes ──────────────────────────────────────────────────────────────────
-- One row per configured Google Drive account/crypt pair.
CREATE TABLE IF NOT EXISTS remotes (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    name                    TEXT NOT NULL UNIQUE,        -- human label e.g. "gdrive1"
    provider                TEXT NOT NULL DEFAULT 'drive',
    base_remote             TEXT NOT NULL,               -- rclone base name e.g. "gdrive1:"
    crypt_remote            TEXT NOT NULL,               -- rclone data crypt e.g. "gdrive1_crypt:"
    secrets_crypt_remote    TEXT,                        -- rclone secrets crypt, if configured
    priority                INTEGER NOT NULL DEFAULT 1,  -- 1 = highest priority
    enabled                 INTEGER NOT NULL DEFAULT 1,
    status                  TEXT NOT NULL DEFAULT 'unknown',  -- ok|full|unauthorized|error|unknown
    capacity_total_gb       REAL,
    capacity_used_gb        REAL,
    capacity_checked_at     TEXT,
    fill_threshold_percent  REAL NOT NULL DEFAULT 95.0,
    authorized_email        TEXT,
    account_display_name    TEXT,
    account_photo_url       TEXT,
    authorized_at           TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ─── sources ──────────────────────────────────────────────────────────────────
-- Managed source paths per host and data class.
CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    host             TEXT NOT NULL DEFAULT 'supermicro.local',
    name             TEXT NOT NULL,
    path             TEXT NOT NULL,
    data_class       TEXT NOT NULL DEFAULT 'config',  -- config|data|secrets|packages
    priority         INTEGER NOT NULL DEFAULT 2,
    enabled          INTEGER NOT NULL DEFAULT 1,
    include_patterns TEXT NOT NULL DEFAULT '["*"]',
    exclude_patterns TEXT NOT NULL DEFAULT '["*.tmp","*.bak","*.swp"]',
    notes            TEXT,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(host, name)
);

-- ─── jobs ─────────────────────────────────────────────────────────────────────
-- Backup job definitions. One row per scheduled or manual job.
CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    host            TEXT NOT NULL DEFAULT 'supermicro.local',

    data_class      TEXT NOT NULL,                   -- config|data|secrets|packages
    remote_id       INTEGER REFERENCES remotes(id) ON DELETE SET NULL,
    mode            TEXT NOT NULL DEFAULT 'copy',    -- copy (default) | sync (opt-in)
    schedule_cron   TEXT,                            -- cron expression or NULL = manual only
    enabled         INTEGER NOT NULL DEFAULT 1,
    extra_flags     TEXT NOT NULL DEFAULT '[]',      -- JSON array of additional rclone flags
    pre_hook        TEXT,                            -- shell command to run before rclone
    notify_on_failure INTEGER NOT NULL DEFAULT 1,
    notify_on_success INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at      TEXT
);

-- ─── runs ─────────────────────────────────────────────────────────────────────
-- APPEND-ONLY. Never UPDATE or DELETE rows here.
CREATE TABLE IF NOT EXISTS runs (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id                  INTEGER NOT NULL REFERENCES jobs(id),
    remote_id               INTEGER NOT NULL REFERENCES remotes(id),
    triggered_by            TEXT NOT NULL DEFAULT 'scheduler',  -- scheduler|manual|restore_drill
    started_at              TEXT NOT NULL,
    finished_at             TEXT,
    status                  TEXT NOT NULL DEFAULT 'running',    -- running|success|partial|failed|cancelled
    exit_code               INTEGER,
    bytes_transferred       INTEGER DEFAULT 0,
    files_transferred       INTEGER DEFAULT 0,
    files_checked           INTEGER DEFAULT 0,
    errors                  INTEGER DEFAULT 0,
    rclone_command          TEXT,
    log_path                TEXT,
    rotated_from_remote_id  INTEGER REFERENCES remotes(id),
    created_at              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ─── run_targets ──────────────────────────────────────────────────────────────
-- Dual-account and multi-target tracking per backup run
CREATE TABLE IF NOT EXISTS run_targets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES runs(id),
    remote_id         INTEGER NOT NULL REFERENCES remotes(id),
    role              TEXT NOT NULL DEFAULT 'primary', -- primary|secondary
    status            TEXT NOT NULL DEFAULT 'running', -- running|success|failed|partial
    exit_code         INTEGER,
    bytes_transferred INTEGER DEFAULT 0,
    files_transferred INTEGER DEFAULT 0,
    files_checked     INTEGER DEFAULT 0,
    errors            INTEGER DEFAULT 0,
    log_path          TEXT,
    rclone_command    TEXT,
    started_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    finished_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);


-- Ensure the application never issues UPDATE/DELETE on runs via trigger.

CREATE TRIGGER IF NOT EXISTS runs_no_update
    BEFORE UPDATE ON runs
    BEGIN SELECT RAISE(ABORT, 'runs table is append-only: UPDATE not permitted'); END;

CREATE TRIGGER IF NOT EXISTS runs_no_delete
    BEFORE DELETE ON runs
    BEGIN SELECT RAISE(ABORT, 'runs table is append-only: DELETE not permitted'); END;

-- ─── restores ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS restores (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_run_id       INTEGER REFERENCES runs(id),
    remote_id           INTEGER NOT NULL REFERENCES remotes(id),
    data_class          TEXT NOT NULL,
    remote_path         TEXT NOT NULL,               -- drive path to restore from
    dest_path           TEXT NOT NULL,               -- local destination
    dest_is_production  INTEGER NOT NULL DEFAULT 0,  -- 0=staging /tmp, 1=operator overrode
    dry_run_done        INTEGER NOT NULL DEFAULT 0,  -- must complete dry-run first
    confirmed           INTEGER NOT NULL DEFAULT 0,  -- operator typed confirmation token
    operator            TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending|dry_run|running|done|failed
    started_at          TEXT,
    finished_at         TEXT,
    files_restored      INTEGER DEFAULT 0,
    log_path            TEXT,
    rclone_command      TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- ─── system_state ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_state (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT OR IGNORE INTO system_state (key, value) VALUES
    ('state',           'ACTIVE'),
    ('active_remote_id', NULL),
    ('sync_mode_enabled','0'),
    ('tailscale_only',  '1');

-- ─── audit_log ────────────────────────────────────────────────────────────────
-- Immutable log of every destructive or significant UI action.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,  -- e.g. job.create, remote.delete, restore.confirm
    target_type TEXT,
    target_id   INTEGER,
    detail      TEXT            -- JSON blob
);

-- ─── settings ─────────────────────────────────────────────────────────────────
-- Windows-parity Google Drive & rclone engine defaults
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

INSERT OR IGNORE INTO settings (key, value) VALUES
    ('reserve_margin_percent', '5.0'),
    ('reserve_margin_gb',      '10.0'),
    ('rclone_tpslimit',        '10'),
    ('rclone_tpslimit_burst',  '10'),
    ('rclone_transfers',       '4'),
    ('rclone_checkers',        '8'),
    ('rclone_chunk_size',      '64M'),
    ('rclone_bwlimit',         '5M'),
    ('rclone_retries',         '5'),
    ('rclone_low_level_retries','10'),
    ('rclone_fast_list',       '1'),
    ('rclone_log_level',       'INFO'),
    ('log_retention_days',     '90'),
    ('staging_dir',            '/tmp/adc-restore');

-- ─── catalog_files ────────────────────────────────────────────────────────────
-- Fingerprint ledger for pre-upload file-level deduplication
CREATE TABLE IF NOT EXISTS catalog_files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    host              TEXT NOT NULL,
    data_class        TEXT NOT NULL,
    abs_path          TEXT NOT NULL,
    file_size         INTEGER NOT NULL,
    mtime_iso         TEXT NOT NULL,
    sha256_hash       TEXT NOT NULL,
    remote_id         INTEGER NOT NULL REFERENCES remotes(id) ON DELETE CASCADE,
    first_seen_run_id INTEGER REFERENCES runs(id),
    last_seen_run_id  INTEGER REFERENCES runs(id),
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(host, remote_id, abs_path)
);

CREATE INDEX IF NOT EXISTS idx_catalog_hash ON catalog_files(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_catalog_path ON catalog_files(host, remote_id, abs_path);

