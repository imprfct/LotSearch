"""Runtime utilities for sharing scheduler state across components."""
from __future__ import annotations

from typing import Optional

from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

_scheduler: Optional[AsyncIOScheduler] = None
_monitor_job: Optional[Job] = None


def configure_scheduler(scheduler: AsyncIOScheduler, monitor_job: Job) -> None:
    """Register scheduler and monitor job for later access."""
    global _scheduler, _monitor_job
    _scheduler = scheduler
    _monitor_job = monitor_job


def update_monitor_interval(minutes: int) -> None:
    """Update monitor job interval if scheduler has been configured."""
    if minutes <= 0:
        raise ValueError("Интервал должен быть положительным")

    if _monitor_job is None:
        return

    trigger = IntervalTrigger(minutes=minutes)
    _monitor_job.reschedule(trigger=trigger)


def get_scheduler() -> Optional[AsyncIOScheduler]:
    return _scheduler


def get_monitor_job() -> Optional[Job]:
    return _monitor_job
