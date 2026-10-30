"""映射端点表示边界：未支持的材料语义不能在规范化后冒充已校验的具体结构。"""

import json

import pytest

from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.application.search import search
from reaction_reference.reaction_analysis.analyze import analyze_reaction


@pytest.mark.parametrize(
    "reactant,mapped_left,expected",
    [
        (
            "C[C@H](O)CC",
            "[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5] |&1:1|",
            "unsupported_mapped_endpoint_structure",
        ),
        (
            "C[C@H](O)CC |&1:1|",
            "[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5]",
            "invalid_declared_material_structure",
        ),
        (
            "C[C@H](O)CC",
            "[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5].[*:6]",
            "unsupported_mapped_endpoint_structure",
        ),
        ("C[C@H](O)CC", "[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5]", None),
    ],
)
def test_mapping_support_requires_supported_endpoint_representations(
    tmp_path, request_factory, reactant, mapped_left, expected
):
    """两侧或声明材料包含未支持语义时应保持未知，合法氧化及产物参考仍保留。"""
    row = {
        "id": 1,
        "product_smiles": ["CCC(C)=O"],
        "reactant_smiles": [reactant],
        "mapped_reaction_smiles": mapped_left + ">>[CH3:1][C:2](=[O:3])[CH2:4][CH3:5]",
    }
    analysis = analyze_reaction(import_native(row))
    assert analysis.state == ("unknown" if expected else "analyzed")
    assert analysis.mapping_support == ("unknown" if expected else "single_mapping_inference")
    if expected:
        assert expected in analysis.reasons
        assert not analysis.formed and not analysis.order_changed
    else:
        assert analysis.order_changed
    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                "CCC(C)=O",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        exact = next(r for r in package.results if r.target_requirements_satisfied)
        assert exact.analysis.state == analysis.state
        assert exact.contribution == ("structure_clue" if expected else "modification")
        assert exact.ranking_features["evidence_quality"]["value"]["mapping_support"] == (
            analysis.mapping_support
        )
    finally:
        source.close()


@pytest.mark.parametrize("suffix", [" |&1:1|", ".[*:6]"])
def test_product_mapping_endpoint_has_the_same_representation_boundary(suffix):
    """映射产物端也必须拒绝未支持语义，不能只校验反应物端。"""
    mapped = "[CH3:1][C@H:2]([OH:3])[CH2:4][CH3:5]"
    record = import_native(
        {
            "id": 1,
            "product_smiles": ["C[C@H](O)CC"],
            "reactant_smiles": ["C[C@H](O)CC"],
            "mapped_reaction_smiles": mapped + ">>" + mapped + suffix,
        }
    )
    analysis = analyze_reaction(record)
    assert analysis.state == "unknown"
    assert analysis.mapping_support == "unknown"
    assert "unsupported_mapped_endpoint_structure" in analysis.reasons
