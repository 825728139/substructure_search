"""材料名称关联回归：结构比较不能丢失未支持语义，再把名称附到另一种材料上。"""

import json

import pytest

from reaction_reference.adapters.sources import JsonlSource, import_native
from reaction_reference.application.search import search


@pytest.mark.parametrize(
    "role,smiles,detail_smiles,associated",
    [
        ("product", "C[C@H](F)Cl", "C[C@H](F)Cl |&1:1|", False),
        ("reactant", "C[C@H](F)Cl", "C[C@H](F)Cl |o1:1|", False),
        ("reagent", "C[C@H](F)Cl", "C[C@H](F)Cl |&1:1|", False),
        ("product", "C[C@H](F)Cl |&1:1|", "C[C@H](F)Cl", False),
        ("solvent", "CC.[Na+]", "CC.[Na+]", False),
        ("catalyst", "*CC", "*CC", False),
        ("product", "CCO", "OCC", True),
        ("reactant", "[13CH3]CO", "OC[13CH3]", True),
        ("reagent", "C[NH3+]", "[NH3+]C", True),
        ("product", "C[C@H](F)Cl", "C[C@@H](F)Cl", False),
        ("product", "CCO |$a;b;c$|", "OCC", True),
    ],
)
def test_name_association_requires_supported_material_identity(
    role, smiles, detail_smiles, associated
):
    """名称仅关联可支持且同身份的具体结构，合法同位素、电荷和注释表示仍可对应。"""
    name = "详情中报告的材料名称"
    record = import_native(
        {
            "id": 1,
            role + "_smiles": [smiles],
            "details": {role + "s": [{"smiles": detail_smiles, "name": name}]},
        }
    )
    assert len(record.materials) == 1
    assert record.materials[0].smiles == smiles
    assert record.materials[0].name == (name if associated else None)


def test_unsupported_detail_name_does_not_replace_valid_target_identity(tmp_path, request_factory):
    """有效目标产物仍可检索，但不附入只属于未支持立体组语义的详情名称。"""
    path = tmp_path / "records.jsonl"
    path.write_text(
        json.dumps(
            {
                "id": 1,
                "product_smiles": ["C[C@H](F)Cl"],
                "details": {
                    "products": [{"smiles": "C[C@H](F)Cl |&1:1|", "name": "混合立体组成材料"}]
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                "C[C@H](F)Cl",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        reference = next(
            reference for reference in package.results if reference.target_requirements_satisfied
        )
        assert reference.material.name is None
        assert reference.material.smiles == "C[C@H](F)Cl"
        assert not reference.preparation_hit
    finally:
        source.close()
