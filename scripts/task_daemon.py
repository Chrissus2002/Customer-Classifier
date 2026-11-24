#!/usr/bin/env python3
"""
Resident task daemon for recurring operational work.
"""

import argparse
import fcntl
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

for path in (str(PROJECT_ROOT), str(APP_DIR), str(SCRIPTS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from daemon_tasks import get_task_registry
from daemon_tasks.base import ScheduledTask, TaskResult
from database import (
    finish_daemon_task_run,
    get_latest_daemon_task_run,
    insert_daemon_task_run,
)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_task_due(task: ScheduledTask, latest_run: dict | None, now: datetime) -> bool:
    if latest_run is None:
        return True

    reference_time = parse_timestamp(latest_run.get("finished_at")) or parse_timestamp(latest_run.get("started_at"))
    if reference_time is None:
        return True

    status = latest_run.get("status")
    wait_interval = task.interval
    if status in {"error", "running"}:
        wait_interval = task.error_retry_interval

    return now >= reference_time + wait_interval


def run_task(task: ScheduledTask, tenant_id: int, trigger: str) -> TaskResult:
    started_at = datetime.now(timezone.utc)
    run_row, ok = insert_daemon_task_run(
        tenant_id=tenant_id,
        task_name=task.name,
        trigger=trigger,
        status="running",
        started_at=started_at.isoformat(),
    )

    if not ok:
        print(f"[daemon] could not create task run row for {task.name}: {run_row}")
        run_id = None
    else:
        run_id = run_row["id"]

    try:
        result = task.run(tenant_id)
    except Exception as exc:  # pragma: no cover - defensive path
        result = TaskResult.error(f"Unhandled exception: {exc}")

    finished_at = datetime.now(timezone.utc)
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)

    if run_id is not None:
        update_result, updated = finish_daemon_task_run(
            run_id=run_id,
            status=result.status,
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            result=result.result,
            error_message=result.error_message,
            notes=result.notes,
        )
        if not updated:
            print(f"[daemon] could not finalize task run {run_id}: {update_result}")

    if result.status == "success":
        drift = result.result.get("contact_drift")
        print(f"[daemon] {task.name} success for tenant {tenant_id} in {duration_ms}ms (drift={drift})")
    elif result.status == "skipped":
        print(f"[daemon] {task.name} skipped for tenant {tenant_id}: {result.notes}")
    else:
        print(f"[daemon] {task.name} failed for tenant {tenant_id}: {result.error_message}")

    return result


def select_tasks(task_name: str) -> list[ScheduledTask]:
    registry = get_task_registry()
    if task_name == "all":
        return list(registry.values())
    if task_name not in registry:
        available = ", ".join(sorted(registry))
        raise ValueError(f"Unknown task '{task_name}'. Available tasks: {available}")
    return [registry[task_name]]


def daemon_loop(tenant_id: int, task_name: str, poll_seconds: int) -> None:
    tasks = select_tasks(task_name)
    while True:
        now = datetime.now(timezone.utc)
        for task in tasks:
            latest_run, ok = get_latest_daemon_task_run(tenant_id, task.name)
            if not ok:
                print(f"[daemon] warning: could not load latest run for {task.name}: {latest_run}")
                latest_run = None

            if is_task_due(task, latest_run, now):
                run_task(task, tenant_id, trigger="daemon")

        time.sleep(poll_seconds)


def run_once(tenant_id: int, task_name: str) -> None:
    tasks = select_tasks(task_name)
    for task in tasks:
        run_task(task, tenant_id, trigger="manual")


@contextmanager
def daemon_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Could not acquire daemon lock at {lock_path}") from exc
        yield


def parse_args():
    parser = argparse.ArgumentParser(description="Run the Dialo CX task daemon")
    parser.add_argument("--tenant-id", type=int, required=True, help="Tenant ID to process")
    parser.add_argument("--run-once", action="store_true", help="Run the selected task(s) once and exit")
    parser.add_argument("--task", default="all", help="Task name to run, or 'all'")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Daemon loop sleep interval")
    return parser.parse_args()


def main():
    args = parse_args()
    lock_path = Path.home() / ".local" / "state" / "dialo-cx" / "daemon.lock"

    try:
        with daemon_lock(lock_path):
            if args.run_once:
                run_once(args.tenant_id, args.task)
            else:
                daemon_loop(args.tenant_id, args.task, args.poll_seconds)
    except RuntimeError as exc:
        print(f"[daemon] {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("[daemon] stopped")


if __name__ == "__main__":
    main()
