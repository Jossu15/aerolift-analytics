import os
import sys
import tempfile

# Ensure the repo root (package parent) is importable regardless of
# where pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# API tests run against an isolated throwaway SQLite database; this must
# be set before api.database is imported anywhere.
if "DATABASE_URL" not in os.environ:
    _tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    _tmp_db.close()
    os.environ["DATABASE_URL"] = "sqlite:///{}".format(
        _tmp_db.name.replace("\\", "/"))
