import sys
import types
from unittest.mock import MagicMock, patch

if "streamlit" not in sys.modules:
    streamlit_stub = types.SimpleNamespace(cache_data=lambda **_: (lambda fn: fn))
    sys.modules["streamlit"] = streamlit_stub

import app.database as database


def test_count_distinct_normalized_phones_calls_bronze_rpc():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = 42
    mock_client.schema.return_value.rpc.return_value.execute.return_value = mock_response

    with patch.object(database, "get_supabase_client", return_value=mock_client):
        result, ok = database.count_distinct_normalized_phones(["5218123456789", "5228123456789"])

    assert ok is True
    assert result == 42
    mock_client.schema.assert_called_once_with("bronze")
    mock_client.schema.return_value.rpc.assert_called_once_with(
        "count_distinct_normalized_phones",
        {"p_phones": ["5218123456789", "5228123456789"]},
    )


def test_count_distinct_normalized_phones_handles_empty_list_response():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = []
    mock_client.schema.return_value.rpc.return_value.execute.return_value = mock_response

    with patch.object(database, "get_supabase_client", return_value=mock_client):
        result, ok = database.count_distinct_normalized_phones([])

    assert ok is True
    assert result == 0


def test_count_distinct_normalized_phones_returns_error_on_rpc_failure():
    mock_client = MagicMock()
    mock_client.schema.return_value.rpc.return_value.execute.side_effect = RuntimeError("boom")

    with patch.object(database, "get_supabase_client", return_value=mock_client):
        result, ok = database.count_distinct_normalized_phones(["5218123456789"])

    assert ok is False
    assert "boom" in result


def test_get_contact_identity_count_by_tenant_uses_parser_for_missing_shadow_keys():
    contacts = [
        {
            "contact_id": "contact-1",
            "phone_normalized": "5218123456789",
            "phone_raw": "5218123456789",
            "wati_contact_id": "mx-a",
            "wati_lookup_phone": "5218123456789",
            "phone_identity_key": None,
        },
        {
            "contact_id": "contact-2",
            "phone_normalized": "528123456789",
            "phone_raw": "+52 81 2345 6789",
            "wati_contact_id": "mx-b",
            "wati_lookup_phone": "5218123456789",
            "phone_identity_key": None,
        },
    ]

    with patch.object(database, "get_all_contacts_by_tenant", return_value=contacts):
        result, ok = database.get_contact_identity_count_by_tenant(310131, default_region="MX")

    assert ok is True
    assert result == 1


def test_upsert_contact_wati_key_rows_calls_silver_upsert():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.data = [{"tenant_id": 310131, "wati_contact_id": "wati-1"}]
    mock_client.schema.return_value.table.return_value.upsert.return_value.execute.return_value = mock_response
    rows = [{"tenant_id": 310131, "contact_id": "contact-1", "wati_contact_id": "wati-1"}]

    with patch.object(database, "get_supabase_client", return_value=mock_client):
        result, ok = database.upsert_contact_wati_key_rows(rows)

    assert ok is True
    assert result == 1
    mock_client.schema.assert_called_once_with("silver")
    mock_client.schema.return_value.table.return_value.upsert.assert_called_once_with(
        rows,
        on_conflict="tenant_id,wati_contact_id",
    )
