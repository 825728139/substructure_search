"""查询入口与规划回归：防止多行结构被截断，以及无环核心生成重复计算路径。"""

import json

import pytest
from fastapi.testclient import TestClient
from rdkit import Chem

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.chemistry.structures import StructureError, canonical, parse
from reaction_reference.interfaces.api import create_app
from reaction_reference.retrieval.planner import functional_matches, plan_families


@pytest.mark.parametrize("target", [False, True])
@pytest.mark.parametrize("smiles", ["CCO\nCCN", "CCO\r\nCCN", "CCO\n\nCCN"])
def test_multiline_smiles_cannot_silently_drop_a_structure(smiles, target):
    """目标和来源结构都必须拒绝含多个非空行的输入，不能只解释第一种分子。"""
    with pytest.raises(StructureError):
        parse(smiles, target=target)


@pytest.mark.parametrize("smiles", [" \nCCO\r\n", "CCO |$a;b;c$|", "[13CH3]CO"])
def test_single_structure_whitespace_and_cx_annotations_remain_supported(smiles):
    """外围空白、单行 CX 标签与同位素仍应保留原本的具体结构语义。"""
    assert canonical(parse(smiles, target=True)) == ("[13CH3]CO" if "13CH3" in smiles else "CCO")


@pytest.mark.parametrize("case", ["preview", "submit", "excluded_material"])
def test_http_rejects_multiline_structure_before_accepting_a_job(settings, case):
    """HTTP 预览、检索和排除材料校验应拒绝多行结构，且不落盘错误任务。"""
    request = {"target": {"value": "CCO\nCCN"}}
    endpoint = "/v1/query-families/preview" if case == "preview" else "/v1/search-runs"
    if case == "excluded_material":
        request = {
            "target": {"value": "CCO"},
            "lab_context": {"excluded_material_smiles": ["CCO\nCCN"]},
        }
    with TestClient(create_app(settings)) as client:
        response = client.post(endpoint, json=request)
        assert response.status_code == 422, response.text
        assert not list(settings.store_path.glob("*/state.json"))


def test_jsonl_multiline_material_is_isolated_without_losing_other_records(tmp_path):
    """来源 JSONL 中转义换行的材料必须报告结构问题，相邻有效反应仍可检索。"""
    path = tmp_path / "materials.jsonl"
    path.write_text(
        "".join(
            json.dumps({"id": number, "product_smiles": [smiles]}) + "\n"
            for number, smiles in [(1, "CCO\nCCN"), (2, "CCN")]
        ),
        encoding="utf-8",
    )
    source = JsonlSource(path)
    try:
        assert [item.record.id for item, _, _ in source.candidates] == ["patent:2"]
        assert any(issue.get("record_id") == "patent:1" for issue in source.issues)
    finally:
        source.close()


@pytest.mark.parametrize("smiles", ["CC(O)CC(O)CCN", "OCCC(CO)(CN)CCO", "CCCC", "CCO"])
def test_acyclic_core_preserves_all_anchor_connecting_paths(smiles):
    """优化后的无环核心应与所有原始官能团锚点之间的路径并集完全一致。"""
    target = parse(smiles, target=True)
    anchors = sorted({index for _, match, _ in functional_matches(target) for index in match})
    expected = set(anchors)
    for offset, left in enumerate(anchors):
        for right in anchors[offset + 1 :]:
            expected.update(Chem.GetShortestPath(target, left, right))
    if not anchors:
        expected = {atom.GetIdx() for atom in target.GetAtoms() if atom.GetAtomicNum() > 1}
    core = next(family for family in plan_families(target) if family.layer == "core")
    assert set(core.target_atoms) == expected


def test_large_acyclic_planning_does_not_expand_all_anchor_pairs(monkeypatch):
    """大量官能团的合法目标只需线性次路径连接，避免查询预览被两两路径计算拖慢。"""
    target = parse("CC(O)" * 150, target=True)
    anchors = {index for _, match, _ in functional_matches(target) for index in match}
    shortest_path = Chem.GetShortestPath
    calls = []

    def counted_path(molecule, left, right):
        """记录实际图路径调用次数，避免用不稳定的机器耗时作为回归断言。"""
        calls.append((left, right))
        return shortest_path(molecule, left, right)

    monkeypatch.setattr(Chem, "GetShortestPath", counted_path)
    families = plan_families(target)
    core = next(family for family in families if family.layer == "core")
    assert anchors <= set(core.target_atoms)
    assert len(calls) <= len(anchors) - 1
