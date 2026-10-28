"""Project checks; run using uv run python scripts/check.py from implementation/."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from reaction_reference.schema_export import export_schemas

root = Path(__file__).resolve().parents[1]
os.chdir(root)
for arguments in [
    ("ruff", "check", "--config", "pyproject.toml", "."),
    ("ruff", "format", "--config", "pyproject.toml", "--check", "."),
    ("mypy", "--config-file", "pyproject.toml", "src/reaction_reference"),
    ("pytest", "-q"),
]:
    subprocess.run([sys.executable, "-m", *arguments], check=True)

with tempfile.TemporaryDirectory() as temporary:
    fresh = Path(temporary)
    export_schemas(fresh)
    for path in fresh.glob("*.json"):
        committed = root / "contracts" / path.name
        if not committed.is_file() or json.loads(path.read_text()) != json.loads(
            committed.read_text()
        ):
            raise SystemExit(f"Schema drift: regenerate contracts/{path.name}")
subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation"], check=True)
print("Project checks passed")
