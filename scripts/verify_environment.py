"""验证已安装的依赖并运行现有检查脚本，不改动受版本管理的检查产物。

此处检查开发环境，不代替业务检索引擎的回归测试。
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
    """核对 Python 与依赖、运行本地接口和化学检查、隔离渲染设计图，并将环境报告写入缓存目录。"""
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Run this checker using the project's Python 3.12 environment.")
    versions = {}
    for distribution, module in PACKAGES.items():
        importlib.import_module(module)
        versions[distribution] = version(distribution)

    # 检查 API、HTTP 客户端与严格契约校验库能够配合使用。
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from pydantic import BaseModel, ConfigDict
    from rdkit import Chem
    from rdkit.Chem import Draw

    class Input(BaseModel):
        """本地冒烟接口的严格输入契约，只接受字符串形式的 SMILES。"""
        model_config = ConfigDict(strict=True)
        smiles: str

    app = FastAPI()

    # 这里创建临时应用，仅供本地冒烟检查使用。
    @app.post("/smoke")
    async def smoke(payload: Input) -> dict[str, int | bool]:
        """解析请求中的 SMILES，返回是否有效及原子数，仅供环境联调检查。"""
        molecule = Chem.MolFromSmiles(payload.smiles)
        return {
            "valid": molecule is not None,
            "atoms": 0 if molecule is None else molecule.GetNumAtoms(),
        }

    async def check_api() -> None:
        """使用内存 ASGI 客户端检查合法结构与错误字段类型的响应，受十秒异步超时限制。"""
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

        # 在隔离副本中渲染，避免改动已经提交的设计图。
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
