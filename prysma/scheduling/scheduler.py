"""Scheduler for Prysma — Manages periodic tasks."""
import asyncio
from datetime import datetime
from typing import Callable

from prysma.config import config


class Scheduler:
    """Simple async scheduler for periodic tasks."""

    def __init__(self):
        self.tasks = []
        self.running = False

    def add_task(self, name: str, interval_hours: int, func: Callable):
        """Add a periodic task."""
        self.tasks.append({
            'name': name,
            'interval_hours': interval_hours,
            'func': func,
            'last_run': None
        })

    async def run(self):
        """Run the scheduler loop."""
        self.running = True
        print(f"[{datetime.now()}] Scheduler started with {len(self.tasks)} tasks")

        while self.running:
            now = datetime.now()

            for task in self.tasks:
                if task['last_run'] is None or \
                   (now - task['last_run']).total_seconds() >= task['interval_hours'] * 3600:
                    try:
                        print(f"[{now}] Running task: {task['name']}")
                        task['func']()
                        task['last_run'] = now
                    except Exception as e:
                        print(f"  Error in {task['name']}: {e}")

            await asyncio.sleep(60)  # Check every minute

    def stop(self):
        """Stop the scheduler."""
        self.running = False


def create_default_scheduler() -> Scheduler:
    """Create scheduler with default Prysma tasks."""
    scheduler = Scheduler()

    # Scan cycle
    from prysma.main import run_scan_cycle
    scheduler.add_task('scan_cycle', config.scan_interval_hours, run_scan_cycle)

    # Daily digest
    from prysma.main import run_digest
    scheduler.add_task('daily_digest', 24, run_digest)

    return scheduler
