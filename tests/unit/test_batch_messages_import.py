from batch_messages_import import run_imports


def test_run_imports_dry_run_uses_wati_lookup_phone(monkeypatch, capsys):
    monkeypatch.setattr(
        "batch_messages_import.get_tenant_credentials",
        lambda tenant_id: ({"name": "Filippa", "wati_api_token": "token"}, True),
    )
    monkeypatch.setattr(
        "batch_messages_import.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-1",
                "name": "Ana",
                "wati_lookup_phone": "5218123456789",
                "phone_normalized": None,
                "wati_contact_id": "wati-1",
            }
        ],
    )

    exit_code = run_imports(310131, dry_run=True)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "5218123456789" in output


def test_run_imports_from_file_matches_wati_lookup_phone(monkeypatch, tmp_path, capsys):
    wanted_path = tmp_path / "wanted.txt"
    wanted_path.write_text("5218123456789\n")

    monkeypatch.setattr(
        "batch_messages_import.get_tenant_credentials",
        lambda tenant_id: ({"name": "Filippa", "wati_api_token": "token"}, True),
    )
    monkeypatch.setattr(
        "batch_messages_import.get_all_contacts_by_tenant",
        lambda tenant_id: [
            {
                "contact_id": "contact-1",
                "name": "Ana",
                "wati_lookup_phone": "5218123456789",
                "phone_normalized": "legacy-ignored",
                "wati_contact_id": "wati-1",
            }
        ],
    )

    exit_code = run_imports(310131, from_file=str(wanted_path), dry_run=True)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Filtered to 1 contact(s)" in output
