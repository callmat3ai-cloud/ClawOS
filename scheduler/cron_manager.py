"""
scheduler/cron_manager.py — ClawOS Cron Jobs

Hermes-style natural language scheduling via APScheduler.
"Every morning at 9" → 0 9 * * *
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_LOCK = threading.Lock()


def _base_dir() -> Path:
    frozen = getattr(sys := __import__("sys").modules["sys"], "frozen", False)
    if frozen:
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _get_profile_db_path(profile_id: str) -> Path:
    from memory.profile_manager import _profiles_dir, _init_db
    return _profiles_dir() / f"{profile_id}.db"


def _get_scheduler(profile_id: str | None = None) -> BackgroundScheduler:
    return BackgroundScheduler()


def _parse_natural_cron(text: str) -> tuple[str, str] | None:
    """Convert natural language to cron expression. Returns (cron_expr, description) or None."""
    text = text.lower().strip()

    # Every X minutes
    m = re.match(r"every\s+(\d+)\s+min(?:ute|utes?)", text)
    if m:
        return f"*/{m.group(1)} * * * *", f"Every {m.group(1)} minutes"

    # Every hour
    if "every hour" in text:
        return "0 * * * *", "Every hour"

    # Every N hours
    m = re.match(r"every\s+(\d+)\s+hours?", text)
    if m:
        return f"0 */{m.group(1)} * * *", f"Every {m.group(1)} hours"

    # Every day at HH:MM
    m = re.match(r"every day at (\d{1,2}):(\d{2})", text)
    if m:
        return f"{m.group(2)} {m.group(1)} * * *", f"Every day at {m.group(1)}:{m.group(2)}"

    # Every day at HHam/pm
    m = re.match(r"every day at (\d{1,2})(am|pm)", text)
    if m:
        hour = int(m.group(1)) % 12 + (12 if m.group(2) == "pm" else 0)
        return f"0 {hour} * * *", f"Every day at {hour}:00"

    # Every morning at HH
    m = re.match(r"every morning at (\d{1,2})(am)?", text)
    if m:
        hour = int(m.group(1)) % 12 + (0 if m.group(1) == "12" else (12 if m.group(2) != "am" else 0))
        if m.group(2) == "am" or m.group(1) == "12":
            hour = int(m.group(1)) % 12
            if m.group(2) != "am" and int(m.group(1)) != 12:
                hour += 12
        return f"0 {hour} * * *", f"Every morning at {hour}:00"

    # Every weekday at HH
    m = re.match(r"every weekday at (\d{1,2})(am|pm)?", text)
    if m:
        hour = int(m.group(1))
        if m.group(2) == "pm" and hour != 12:
            hour += 12
        elif m.group(2) != "pm" and hour == 12:
            hour = 0
        return f"0 {hour} * * 1-5", f"Every weekday at {hour}:00"

    # Every week on DAY at HH
    day_map = {"monday": "1", "tuesday": "2", "wednesday": "3",
               "thursday": "4", "friday": "5", "saturday": "6", "sunday": "0"}
    m = re.match(r"every (\w+day) at (\d{1,2})(am|pm)?", text)
    if m and m.group(1).lower() in day_map:
        hour = int(m.group(2))
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        elif m.group(3) != "pm" and hour == 12:
            hour = 0
        return f"0 {hour} * * {day_map[m.group(1).lower()]}", f"Every {m.group(1)} at {hour}:00"

    return None


# ── Public API ────────────────────────────────────��────────────

class CronManager:
    """Manages scheduled cron jobs per profile."""

    def __init__(self):
        self._schedulers: dict[str, BackgroundScheduler] = {}
        self._lock = threading.Lock()

    def _get_sched(self, profile_id: str) -> BackgroundScheduler:
        with self._lock:
            if profile_id not in self._schedulers:
                sched = BackgroundScheduler()
                sched.start()
                self._schedulers[profile_id] = sched
            return self._schedulers[profile_id]

    def schedule_job(
        self,
        name: str,
        natural_cron: str,
        action: str,
        profile_id: str | None = None,
    ) -> dict:
        """Schedule a job from natural language. Returns {id, cron_expr, description}."""
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()

        parsed = _parse_natural_cron(natural_cron)
        if not parsed:
            return {"error": f"Could not parse: '{natural_cron}'"}

        cron_expr, description = parsed
        job_id = f"cron_{uuid.uuid4().hex[:8]}"

        # Store in DB
        db_path = _get_profile_db_path(profile_id)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT OR REPLACE INTO cron_jobs (id, name, cron_expr, action) VALUES (?, ?, ?, ?)",
            (job_id, name, cron_expr, action),
        )
        conn.commit()
        conn.close()

        # Add to scheduler
        sched = self._get_sched(profile_id)
        sched.add_job(
            func=self._run_job,
            trigger=CronTrigger.from_crontab(cron_expr),
            id=job_id,
            name=name,
            args=[job_id, action, profile_id],
            replace_existing=True,
        )

        return {
            "id": job_id,
            "name": name,
            "cron_expr": cron_expr,
            "description": description,
            "profile_id": profile_id,
        }

    def _run_job(self, job_id: str, action: str, profile_id: str):
        """Execute a cron job action."""
        import logging
        logging.info(f"[Cron] Running job {job_id}: {action}")

        # Update last_run in DB
        db_path = _get_profile_db_path(profile_id)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE cron_jobs SET last_run=CURRENT_TIMESTAMP WHERE id=?", (job_id,)
        )
        conn.commit()
        conn.close()

        # Dispatch action via executor
        try:
            from agent.executor import AgentExecutor
            executor = AgentExecutor()
            result = executor.execute(
                goal=f"Cron job: {action}",
                speak=None,
                cancel_flag=threading.Event(),
            )
            logging.info(f"[Cron] Job {job_id} completed: {result[:100]}")
        except Exception as e:
            logging.error(f"[Cron] Job {job_id} failed: {e}")

    def list_jobs(self, profile_id: str | None = None) -> list[dict]:
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()
        db_path = _get_profile_db_path(profile_id)
        if not db_path.exists():
            return []
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT id, name, cron_expr, action, enabled, last_run, created_at FROM cron_jobs"
            ).fetchall()
            return [
                {
                    "id": r[0], "name": r[1], "cron_expr": r[2],
                    "action": r[3], "enabled": bool(r[4]),
                    "last_run": r[5], "created_at": r[6],
                }
                for r in rows
            ]
        finally:
            conn.close()

    def remove_job(self, job_id: str, profile_id: str | None = None) -> bool:
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()
        sched = self._get_sched(profile_id)
        try:
            sched.remove_job(job_id)
        except Exception:
            pass
        db_path = _get_profile_db_path(profile_id)
        conn = sqlite3.connect(str(db_path))
        conn.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        return True

    def pause_job(self, job_id: str, profile_id: str | None = None) -> bool:
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()
        db_path = _get_profile_db_path(profile_id)
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE cron_jobs SET enabled=0 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        sched = self._get_sched(profile_id)
        try:
            sched.pause_job(job_id)
        except Exception:
            pass
        return True

    def resume_job(self, job_id: str, profile_id: str | None = None) -> bool:
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()
        db_path = _get_profile_db_path(profile_id)
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE cron_jobs SET enabled=1 WHERE id=?", (job_id,))
        conn.commit()
        conn.close()
        sched = self._get_sched(profile_id)
        try:
            sched.resume_job(job_id)
        except Exception:
            pass
        return True

    def restore_all(self, profile_id: str | None = None):
        """Restore all jobs from DB on app startup."""
        from memory.profile_manager import get_active_profile
        if profile_id is None:
            profile_id = get_active_profile()
        jobs = self.list_jobs(profile_id)
        sched = self._get_sched(profile_id)
        for job in jobs:
            if not job["enabled"]:
                continue
            try:
                sched.add_job(
                    func=self._run_job,
                    trigger=CronTrigger.from_crontab(job["cron_expr"]),
                    id=job["id"],
                    name=job["name"],
                    args=[job["id"], job["action"], profile_id],
                    replace_existing=True,
                )
            except Exception as e:
                import logging
                logging.warning(f"[Cron] Could not restore job {job['id']}: {e}")


# Singleton
_manager: CronManager | None = None


def get_cron_manager() -> CronManager:
    global _manager
    if _manager is None:
        _manager = CronManager()
    return _manager
