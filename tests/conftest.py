"""Test environment. Runs before the application modules are imported."""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Isolated calibration database; tests must never reach the real Anthropic API.
os.environ["SQLITE_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="qe_tests_")) / "hitl.db")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["REQUIRE_AUTH"] = "false"
os.environ.pop("API_AUTH_TOKEN", None)
