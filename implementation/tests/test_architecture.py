"""回归测试：代码依赖方向、规则与契约约束。"""

import ast
import json
from pathlib import Path

from reaction_reference.domain.models import SearchRequest
from reaction_reference.rules import load_rules

ROOT = Path(__file__).resolve().parents[1]


def test_domain_and_chemical_layers_do_not_import_adapters_or_interfaces():
    """检查领域、化学与应用模块不反向导入具体适配器/接口；领域也不依赖 RDKit、HTTP 或 PG。"""
    for area in (
        "domain",
        "ports",
        "chemistry",
        "retrieval",
        "reaction_analysis",
        "evidence",
        "ranking",
        "analogs",
        "application",
    ):
        for path in (ROOT / "src/reaction_reference" / area).glob("*.py"):
            tree = ast.parse(path.read_text())
            for statement in ast.walk(tree):
                if isinstance(statement, ast.ImportFrom) and statement.module:
                    assert not statement.module.startswith(
                        ("reaction_reference.adapters", "reaction_reference.interfaces")
                    ), path
                    if area == "domain":
                        assert not statement.module.startswith(("rdkit", "fastapi", "psycopg")), (
                            path
                        )


def test_rules_compile_and_have_regression_scope():
    """确认随包规则可编译、含内容哈希并显式列出未支持范围。"""
    rules, content_hash = load_rules()
    assert len(content_hash) == 64 and rules["functional_groups"] and rules["transfer_rules"]
    assert rules["unsupported"]


def test_contract_schema_is_exported():
    """比较已提交请求 Schema 与当前模型导出，防止接口契约悄然漂移。"""
    path = ROOT / "contracts/SearchRequest.schema.json"
    assert json.loads(path.read_text()) == SearchRequest.model_json_schema()
