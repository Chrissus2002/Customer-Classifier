import io

import wati_supabase_cli as cli


def test_parse_args_status_command():
    args = cli.parse_args(["status", "--tenant-id", "310131"])

    assert args.command == "status"
    assert args.tenant_id == 310131
    assert args.handler == cli.handle_status


def test_parse_args_watch_status_command():
    args = cli.parse_args(["watch", "status", "--tenant-id", "310131", "--interval", "5"])

    assert args.command == "watch"
    assert args.watch_command == "status"
    assert args.tenant_id == 310131
    assert args.interval == 5
    assert args.handler == cli.handle_watch_status


def test_main_status_routes_to_status_formatter(monkeypatch, capsys):
    captured = []
    snapshot = cli.StatusSnapshot(
        tenant_id=310131,
        tenant_name="Filippa",
        tenant_slug="filippa",
        wati_api_configured=True,
        wati_phone_number="+5218112089229",
        drift_run=None,
        active_job=None,
    )

    monkeypatch.setattr(cli, "load_status_snapshot", lambda tenant_id: snapshot)
    monkeypatch.setattr(
        cli,
        "format_status",
        lambda loaded: captured.append(loaded) or "formatted status\n",
    )

    exit_code = cli.main(["status", "--tenant-id", "310131"])

    assert exit_code == 0
    assert captured == [snapshot]
    assert capsys.readouterr().out == "formatted status\n"


def test_format_status_includes_drift_and_job_details():
    snapshot = cli.StatusSnapshot(
        tenant_id=310131,
        tenant_name="Filippa",
        tenant_slug="filippa",
        wati_api_configured=True,
        wati_phone_number="+5218112089229",
        drift_run={
            "status": "success",
            "started_at": "2026-04-15T09:12:00+00:00",
            "result": {
                "wati_distinct_contact_count": 8888,
                "db_contact_count": 8888,
                "wati_only_count": 0,
                "db_only_count": 0,
                "exact_match": True,
            },
        },
        active_job={
            "job_id": "job-123",
            "status": "running",
            "processed_messages": 10,
            "total_messages": 20,
            "created_at": "2026-04-15T09:00:00+00:00",
            "subprocess_pid": 4321,
        },
    )

    output = cli.format_status(snapshot)

    assert "Filippa (310131)" in output
    assert "configured" in output
    assert "Exact drift: success" in output
    assert "8,888" in output
    assert "Active import job: running (10/20)" in output
    assert "job-123" in output
