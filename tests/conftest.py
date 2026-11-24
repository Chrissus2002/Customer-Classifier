"""
Root conftest — adds scripts/ to sys.path so tests can import classifier modules.
Also mocks supabase_client at the module level to avoid requiring real credentials.
"""
import sys
import types
import builtins
from pathlib import Path
from unittest.mock import MagicMock

# Add scripts/ to path so `from classifiers.xxx import ...` works
project_root = Path(__file__).parent.parent
app_dir = project_root / "app"
scripts_dir = Path(__file__).parent.parent / "scripts"
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

# Shared test tenant used by older unit tests that reference the name directly.
builtins.YOUR_TENANT_ID = 310131

# Minimal streamlit stub so app.database imports in unit tests.
if "streamlit" not in sys.modules:
    streamlit_stub = types.SimpleNamespace(cache_data=lambda **_: (lambda fn: fn))
    sys.modules["streamlit"] = streamlit_stub

# Minimal google.genai stub for GeminiClassifier constructor tests. The real
# SDK remains optional at runtime and is only needed for live Gemini calls.
if "google" not in sys.modules:
    google_stub = types.ModuleType("google")
    sys.modules["google"] = google_stub
else:
    google_stub = sys.modules["google"]

if not hasattr(google_stub, "genai"):
    genai_stub = types.SimpleNamespace(
        Client=lambda **_: MagicMock(),
        types=types.SimpleNamespace(GenerateContentConfig=MagicMock()),
    )
    google_stub.genai = genai_stub
    sys.modules["google.genai"] = genai_stub

# Stub out supabase_client before any module imports it
if "supabase_client" not in sys.modules:
    stub = MagicMock()
    stub.get_supabase_client.return_value = MagicMock()
    sys.modules["supabase_client"] = stub
