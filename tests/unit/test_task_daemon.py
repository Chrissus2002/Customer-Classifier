from datetime import datetime, timedelta, timezone

import pytest

import task_daemon
from daemon_tasks.base import TaskResult


class DummyTask:
    name = "dummy"
    interval = timedelta(hours=4)
    error_retry_interval = timedelta(minutes=15)

    def __init__(self, result=None, exc=None):
        self._result = result or TaskResult.success({"ok": True})
        self._exc = exc

    def run(self, tenant_id):
        if self._exc is not None:
            raise self._exc
        return self._result


def test_is_task_due_when_no_previous_run():
    now = datetime.now(timezone.utc)

    assert task_daemon.is_task_due(DummyTask(), None, now) is True


def test_is_task_due_uses_error_retry_interval_for_failed_runs():
    task = DummyTask()
    now = datetime(2026, 4, 15, 12, 0, tzinfo=timezone.utc)
    latest_run = {
        "status": "error",
        "finished_at": "2026-04-15T11:50:00+00:00",
    }

    assert task_daemon.is_task_due(task, latest_run, now) is False
    assert task_daemon.is_task_due(task, latest_run, now + timedelta(minutes=6)) is True


def test_run_task_records_unhandled_exception_as_error(monkeypatch):
    started_rows = []
    finished_rows = []

    def fake_insert_daemon_task_run(**kwargs):
        started_rows.append(kwargs)
        return {"id": "run-1"}, True

    def fake_finish_daemon_task_run(**kwargs):
        finished_rows.append(kwargs)
        return {"id": "run-1"}, True

    monkeypatch.setattr(task_daemon, "insert_daemon_task_run", fake_insert_daemon_task_run)
    monkeypatch.setattr(task_daemon, "finish_daemon_task_run", fake_finish_daemon_task_run)

    result = task_daemon.run_task(DummyTask(exc=RuntimeError("boom")), tenant_id=310131, trigger="manual")

    assert result.status == "error"
    assert "boom" in result.error_message
    assert started_rows[0]["trigger"] == "manual"
    assert finished_rows[0]["status"] == "error"


def test_run_once_uses_manual_trigger(monkeypatch):
    captured = []

    monkeypatch.setattr(task_daemon, "select_tasks", lambda task_name: [DummyTask()])
    monkeypatch.setattr(task_daemon, "run_task", lambda task, tenant_id, trigger: captured.append((task.name, tenant_id, trigger)))

    task_daemon.run_once(tenant_id=310131, task_name="all")

    assert captured == [("dummy", 310131, "manual")]


def test_select_tasks_rejects_unknown_task():
    with pytest.raises(ValueError):
        task_daemon.select_tasks("missing")
