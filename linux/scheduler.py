"""
linux/scheduler.py — APScheduler integration for scheduled backup jobs.

Provides pause/resume controls and dynamic job registration.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "/opt/adc-backup/db/state.db")

_scheduler: Optional[BackgroundScheduler] = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def start(db_path: str = DB_PATH) -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        log.info("Scheduler started")
    sync_jobs(db_path)


def sync_jobs(db_path: str = DB_PATH) -> None:
    """
    Sync scheduler jobs with the DB. Adds/removes APScheduler entries
    to match enabled jobs with a schedule_cron value.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from shared.database import get_jobs
    from linux.engine import run_job

    sched = get_scheduler()
    db_jobs = get_jobs(host="linux", db_path=db_path)

    existing_ids = {j.id for j in sched.get_jobs()}
    wanted_ids = set()

    for job in db_jobs:
        if not job["schedule_cron"] or not job["enabled"]:
            continue
        job_key = f"backup_job_{job['id']}"
        wanted_ids.add(job_key)
        if job_key not in existing_ids:
            try:
                sched.add_job(
                    func=run_job,
                    trigger=CronTrigger.from_crontab(job["schedule_cron"]),
                    id=job_key,
                    name=job["name"],
                    kwargs={"job_id": job["id"], "triggered_by": "scheduler", "db_path": db_path},
                    replace_existing=True,
                    misfire_grace_time=300,
                )
                log.info("Scheduled job: %s (%s)", job["name"], job["schedule_cron"])
            except Exception as exc:
                log.error("Failed to schedule job %s: %s", job["name"], exc)

    # Remove stale jobs
    for job_id in existing_ids - wanted_ids:
        if job_id.startswith("backup_job_"):
            sched.remove_job(job_id)
            log.info("Removed scheduler entry: %s", job_id)


def pause_scheduler(db_path: str = DB_PATH) -> None:
    from shared.database import set_system_state
    get_scheduler().pause()
    set_system_state("PAUSED", db_path)
    log.info("Scheduler paused")


def resume_scheduler(db_path: str = DB_PATH) -> None:
    from shared.database import set_system_state
    get_scheduler().resume()
    set_system_state("ACTIVE", db_path)
    log.info("Scheduler resumed")


def is_paused() -> bool:
    sched = get_scheduler()
    return sched.state == 2  # STATE_PAUSED = 2


def remove_job(job_id: int) -> None:
    key = f"backup_job_{job_id}"
    sched = get_scheduler()
    if sched.get_job(key):
        sched.remove_job(key)


def shutdown() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
