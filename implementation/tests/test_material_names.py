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


@pytest.mark.parametrize(
    "names,expected",
    [
        (["乙醇"], "乙醇"),
        ([None], None),
        ([["乙醇"]], None),
        ([{"text": "乙醇"}], None),
        ([42], None),
        ([" \t"], None),
        (["乙醇", "乙醇"], "乙醇"),
        (["乙醇", "另一名称"], None),
        (["乙醇", ["乙醇"]], None),
    ],
)
def test_unusable_optional_names_do_not_discard_structural_records(
    tmp_path, request_factory, names, expected
):
    """名称类型异常或有歧义时保留有效反应和结构命中，不能由可选文本导致整条记录丢失。"""
    row = {
        "id": 1,
        "product_smiles": ["CCO"],
        "details": {"products": [{"smiles": "OCC", "name": name} for name in names]},
    }
    path = tmp_path / "optional-names.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        assert len(source.records) == 1 and not source.issues
        assert source.records[0].materials[0].name == expected
        package = search(
            request_factory(
                "CCO",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        reference = next(r for r in package.results if r.target_requirements_satisfied)
        assert reference.material.name == expected
        assert not reference.preparation_hit
    finally:
        source.close()


@pytest.mark.parametrize(
    "role,entries,expected",
    [
        ("product", True, None),
        ("reactant", 7, None),
        ("reagent", {"smiles": "CCO", "name": "乙醇"}, None),
        ("catalyst", "unexpected", None),
        ("solvent", [{"smiles": "OCC", "name": "乙醇"}], "乙醇"),
        ("product", None, None),
        ("product", False, None),
        ("reactant", 0, None),
        ("product", [7, {"smiles": "OCC", "name": "乙醇"}], "乙醇"),
    ],
)
def test_optional_detail_container_types_preserve_valid_structures(
    tmp_path, request_factory, role, entries, expected
):
    """材料详情容器异常仅失去可选名称；五类角色的有效结构和目标命中继续保留。"""
    row = {
        "id": 1,
        "product_smiles": ["CCO"],
        role + "_smiles": ["CCO"],
        "details": {role + "s": entries},
    }
    path = tmp_path / "detail-containers.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    source = JsonlSource(path, exhaustive=True)
    try:
        assert len(source.records) == 1 and not source.issues
        material = next(m for m in source.records[0].materials if m.role == role)
        assert material.name == expected
        package = search(
            request_factory(
                "CCO",
                options={"include_usage": False, "include_proposals": False},
                budget={"max_tasks": 100},
            ),
            source,
        )
        reference = next(r for r in package.results if r.target_requirements_satisfied)
        assert next(m for m in reference.record.materials if m.role == role).name == expected
        assert not reference.preparation_hit
    finally:
        source.close()
