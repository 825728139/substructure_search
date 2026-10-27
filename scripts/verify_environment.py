"""Verify installed dependencies and run existing probes without changing tracked outputs.

This validates the development environment, not the planned retrieval engine.
"""

import asyncio
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "rdkit": "rdkit",
    "fastapi": "fastapi",
    "pydantic": "pydantic",
    "pydantic-settings": "pydantic_settings",
    "uvicorn": "uvicorn",
    "httpx": "httpx",
    "pillow": "PIL",
    "pytest": "pytest",
    "pytest-cov": "pytest_cov",
    "pytest-asyncio": "pytest_asyncio",
    "ruff": "ruff",
    "mypy": "mypy",
    "hypothesis": "hypothesis",
    "import-linter": "importlinter",
    "jsonschema": "jsonschema",
    "build": "build",
    "hatchling": "hatchling",
}


def main() -> None:
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this checker using the project's Python 3.12 environment.")
    versions = {}
    for distribution, module in PACKAGES.items():
        importlib.import_module(module)
        versions[distribution] = version(distribution)

    # Verify the API, client and strict contract libraries work together.
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from pydantic import BaseModel, ConfigDict
    from rdkit import Chem
    from rdkit.Chem import Draw

    class Input(BaseModel):
        model_config = ConfigDict(strict=True)
        smiles: str

    app = FastAPI()

    # A local smoke app, not a product endpoint.
    @app.post("/smoke")
    async def smoke(payload: Input) -> dict[str, int | bool]:
        molecule = Chem.MolFromSmiles(payload.smiles)
        return {
            "valid": molecule is not None,
            "atoms": 0 if molecule is None else molecule.GetNumAtoms(),
        }

    async def check_api() -> None:
        async with asyncio.timeout(10):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://local-smoke"
            ) as client:
                good = await client.post("/smoke", json={"smiles": "CCO"})
                assert good.status_code == 200 and good.json() == {"valid": True, "atoms": 3}
                invalid = await client.post("/smoke", json={"smiles": 123})
                assert invalid.status_code == 422

    asyncio.run(check_api())
    print("PASS dependency imports and local ASGI strict-contract smoke", flush=True)

    graphviz = shutil.which("dot")
    if graphviz is None:
        raise SystemExit("Graphviz 'dot' is required for the design diagrams.")
    dot_version = subprocess.run([graphviz, "-V"], capture_output=True, text=True, check=True)

    cache = ROOT / ".cache" / "environment-check"
    cache.mkdir(parents=True, exist_ok=True)
    probe_results = []
    with tempfile.TemporaryDirectory(dir=cache) as scratch:
        scratch_path = Path(scratch)
        Draw.MolToImage(Chem.MolFromSmiles("CCO")).save(scratch_path / "rdkit.png")
        assert (scratch_path / "rdkit.png").stat().st_size > 0
        probes = sorted((ROOT / "reviews").glob("check_*.py"))
        probes += sorted((ROOT / "audits" / "probes").glob("*.py"))
        for index, probe in enumerate(probes):
            work = scratch_path / f"probe-{index}"
            work.mkdir()
            copied = work / probe.name
            shutil.copy2(probe, copied)
            completed = subprocess.run(
                [sys.executable, str(copied)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=120,
                check=False,
            )
            if completed.returncode:
                print(completed.stdout, file=sys.stderr)
                print(completed.stderr, file=sys.stderr)
                completed.check_returncode()
            probe_results.append(
                {"script": str(probe.relative_to(ROOT)), "output": completed.stdout.strip()}
            )
            print(f"PASS {probe.relative_to(ROOT)}: {completed.stdout.strip()}")

        # Rendering runs on an isolated copy to avoid changing committed diagrams.
        renderer = scratch_path / "build_pre_prediction_design.py"
        shutil.copy2(ROOT / "diagrams" / renderer.name, renderer)
        subprocess.run([sys.executable, str(renderer)], cwd=ROOT, timeout=120, check=True)
        rendered = len(list(scratch_path.glob("*.svg")))
        expected = len(list((ROOT / "diagrams").glob("*.svg")))
        assert rendered == expected, (rendered, expected)

    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_design.py")], check=True)
    report = {
        "scope": "development_environment_and_existing_probes_only",
        "validated_at": datetime.now(UTC).isoformat(),
        "python": sys.version.split()[0],
        "python_build": sys.version,
        "packages": versions,
        "graphviz": (dot_version.stderr or dot_version.stdout).strip(),
        "api_strict_contract_smoke": "passed",
        "rdkit_image_smoke": "passed",
        "probes": probe_results,
        "rendered_svg_count": rendered,
        "retrieval_engine_tested": False,
    }
    destination = cache / "latest.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Environment verified. Report: {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
