import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
JBUILD_ROOT = PROJECT_ROOT / "journey-builder"
if str(JBUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(JBUILD_ROOT))


from jbuild.api.main import app, health


def test_api_health_imports_without_ui_runtime():
    assert health() == {"status": "ok", "service": "jbuild"}


def test_api_exposes_trait_routes():
    paths = {route.path for route in app.routes}

    assert "/traits" in paths
    assert "/traits/{trait_id}/values" in paths
    assert "/trait-classifiers/{trait_id}/drafts" in paths
    assert "/trait-classifiers/{trait_id}/activate" in paths
    assert "/trait-classifiers/{trait_id}/tests" in paths


def test_api_routes_do_not_import_ui_layers():
    source = (JBUILD_ROOT / "jbuild" / "api" / "traits.py").read_text()

    assert "streamlit" not in source
    assert "journey-builder/app" not in source
    assert "app.src" not in source
