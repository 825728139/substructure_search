"""映射端点表示边界：未支持的材料语义不能在规范化后冒充已校验的具体结构。"""

import json
from pathlib import Path

import pytest

from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import Reference
from reaction_reference.reaction_analysis.analyze import analyze_reaction, project_changes


@pytest.mark.parametrize(
    "declared,left,valid",
    [
        ("CN.Cl", "[CH3:3][NH2:4].[ClH:5]", True),
        ("C[NH3+].[Cl-]", "[CH3:3][NH3+:4].[Cl-:5]", True),
        ("CN.Cl", "[CH3:3][NH2:4]", False),
        ("CN.Cl", "[CH3:3][NH3+:4].[Cl-:5]", False),
        ("CN.[37ClH]", "[CH3:3][NH2:4].[ClH:5]", False),
        ("CN.Cl.Cl", "[CH3:3][NH2:4].[ClH:5]", False),
        ("CN.*", "[CH3:3][NH2:4].[ClH:5]", False),
    ],
)
def test_salt_endpoint_reconciliation_preserves_all_component_identities(declared, left, valid):
    """盐按组分和份数对账；缺反离子、电荷/同位素不同或虚原子不能被去盐操作掩盖。"""
    record = import_native(
        {
            "id": 1,
            "reactant_smiles": ["CBr", declared],
            "product_smiles": ["CNC"],
            "mapped_reaction_smiles": "[CH3:1][Br:2]." + left + ">>[CH3:3][NH:4][CH3:1]",
        }
    )
    analysis = analyze_reaction(record)
    assert (analysis.state != "unknown") == valid
    if valid:
        assert {c.maps for c in analysis.formed} == {(1, 4)}
        assert record.materials[-1].smiles == declared
        assert all(m.actual_input is None for m in record.materials)
    else:
        assert not analysis.formed


def test_real_hydrazine_salt_cyclization_retains_target_bond_evidence():
    """真实芳基肼盐酸盐先例应恢复吡唑成键投影，但不升级为已验证的目标制备。"""
    payload = json.loads((Path(__file__).parent / "fixtures/salt_cyclization.json").read_text())
    reference = Reference.model_validate_json(json.dumps(payload["reference"]))
    analysis = analyze_reaction(reference.record)
    assert analysis.state == "partial"
    assert {c.maps for c in analysis.formed} == {(6, 14), (8, 13)}
    assert "ring_closure" in analysis.topology
    assert analysis.event_scope == reference.record.event_scope == "unknown"
    assert "partial_mapping" in analysis.reasons
    target = parse(payload["target_smiles"])
    projected = [
        project_changes(reference.record, reference.material, w, analysis, target=target)
        for w in reference.witnesses
    ]
    assert any(len(p["formed_target_bonds"]) == 2 for p in projected)
    assert not reference.obtainment_hit and not reference.preparation_hit


@pytest.mark.parametrize("counterion_present", [True, False])
def test_declared_product_salt_requires_its_counterion(counterion_present):
    """产物盐也按全部组分对账；不能只验证有机部分就认定完整产物端点一致。"""
    side = "[CH3:1][NH3+:2].[Cl-:3]"
    record = import_native(
        {
            "id": 1,
            "reactant_smiles": ["C[NH3+].[Cl-]"],
            "product_smiles": ["C[NH3+].[Cl-]"],
            "mapped_reaction_smiles": side
            + ">>"
            + (side if counterion_present else "[CH3:1][NH3+:2]"),
        }
    )
    analysis = analyze_reaction(record)
    assert (analysis.state == "analyzed") == counterion_present
    if not counterion_present:
        assert "mapped_endpoints_do_not_reconcile_with_material_instances" in analysis.reasons


def test_repeated_declared_salts_do_not_reuse_one_mapped_component():
    """两个声明材料需要各自的组分份数，一份映射盐不能重复抵扣。"""
    record = import_native(
        {
            "id": 1,
            "reactant_smiles": ["CN.Cl", "CN.Cl"],
            "product_smiles": ["CN"],
            "mapped_reaction_smiles": "[CH3:1][NH2:2].[ClH:3]>>[CH3:1][NH2:2]",
        }
    )
    analysis = analyze_reaction(record)
    assert analysis.state == "unknown"
    assert "mapped_endpoints_do_not_reconcile_with_material_instances" in analysis.reasons


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
