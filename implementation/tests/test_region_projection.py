"""反应中心有歧义时的区域级方法支持，区分明确无关、区域共识和枚举不完整。"""

import json
from importlib import import_module
from pathlib import Path

import pytest
from rdkit import Chem

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import Reference
from reaction_reference.ranking.engine import rank_references
from reaction_reference.reaction_analysis.analyze import analyze_reaction, project_changes
from reaction_reference.reaction_analysis.region_support import has_region_method, region_consensus
from reaction_reference.retrieval.planner import initial_families


def bridge_case():
    """加载此前被排除的真实桥环先例，保留当时完整材料、来源和具体匹配见证。"""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/ambiguous_bridge_projection.json").read_text()
    )
    reference = Reference.model_validate_json(json.dumps(payload["reference"]))
    return parse(payload["target_smiles"]), reference, payload["target_smiles"]


def test_real_bridge_retains_region_without_fabricating_exact_target_bond():
    """真实C—C闭环在两个等价目标位置之间有歧义，区域确认不能变成两根确定新键。"""
    target, reference, smiles = bridge_case()
    analysis = analyze_reaction(reference.record)
    witness = next(
        w for w in reference.witnesses if w.id == reference.coverage["method_witness_id"]
    )
    projected = project_changes(
        reference.record, reference.material, witness, analysis, target=target
    )
    assert "ring_closure" in analysis.topology
    assert {change.maps for change in analysis.formed} == {(11, 14)}
    assert projected["formed_target_bonds"] == []
    assert projected["changed_target_atoms"] == []
    assert projected["support"] == "ambiguous_product_mapping"
    assert projected["mapping_alternatives_checked"] == 8
    assert len(projected["projection_alternatives"]) == 2
    assert all(len(a["formed_target_bonds"]) == 1 for a in projected["projection_alternatives"])
    assert has_region_method(projected)
    assert projected["region_consensus"]["kind"] == "core_internal"
    updated = reference.model_copy(
        update={
            "contribution": "local_method",
            "coverage": {
                **reference.coverage,
                "projected_changes": projected,
            },
        }
    )
    ranked, displayed = rank_references([updated], target_smiles=smiles)
    assert displayed == [updated.id]
    assert not any(r.startswith("recommendation_excluded:") for r in ranked[0].reasons)
    assert not ranked[0].obtainment_hit
    spatial = ranked[0].ranking_features["target_scaffold_relevance"]
    score = ranked[0].ranking_features["score"]["components"]
    assert spatial["center_location"] == "core_internal_region_consensus"
    assert score["mapping_certainty"]["value"] == 0.7
    assert score["method_contribution"]["value"] == 0.8


@pytest.mark.parametrize(
    "mode", ["empty_alternative", "different_cores", "remote_tail", "incomplete"]
)
def test_region_consensus_requires_every_complete_alternative_in_same_region(mode):
    """不同母核、远端尾部、某个解释无成键、枚举不完整都不能获得区域共识。"""
    target = parse("c1ccccc1CCc1ccccc1")
    alternatives = [(((0, 1),), (0, 1)), (((1, 2),), (1, 2))]
    if mode == "empty_alternative":
        alternatives[1] = ((), ())
    elif mode == "different_cores":
        alternatives[1] = (((8, 9),), (8, 9))
    elif mode == "remote_tail":
        alternatives[1] = (((6, 7),), (6, 7))
    result = region_consensus(alternatives, target, enumeration_complete=mode != "incomplete")
    assert result["state"] == "unresolved"


def test_ambiguous_head_region_does_not_become_core_internal():
    """直接连接官能团内部的不唯一位置可确认头部区域，不能冒充母核内部成键。"""
    target = parse("CCN(C)C(=O)c1ccccc1")
    result = region_consensus(
        [(((2, 4),), (2, 4)), (((4, 5),), (4, 5))], target, enumeration_complete=True
    )
    assert result["state"] == "confirmed"
    assert result["kind"] == "core_branch_head"


def test_projection_cap_never_certifies_region_from_sampled_mappings(monkeypatch):
    """超过128个对应时，已看过的部分即使都在母核内也不能冒充完整共识。"""
    target, reference, _ = bridge_case()
    analysis = analyze_reaction(reference.record)
    witness = reference.witnesses[0]
    original = Chem.Mol.GetSubstructMatches

    def many_matches(molecule, query, *args, **kwargs):
        """重复合法对应模拟129个候选，仅用于检验枚举上限守卫。"""
        matches = original(molecule, query, *args, **kwargs)
        return (matches * 129)[:129]

    monkeypatch.setattr(Chem.Mol, "GetSubstructMatches", many_matches)
    projected = project_changes(
        reference.record, reference.material, witness, analysis, target=target
    )
    assert projected["formed_target_bonds"] == []
    assert not has_region_method(projected)
    assert projected["region_consensus"]["state"] == "unresolved"


def test_multiple_identical_product_instances_do_not_claim_complete_region_consensus():
    """存在多个同身份产物时，不能只看其中一个实例就声称所有对应都支持同一区域。"""
    target, reference, _ = bridge_case()
    analysis = analyze_reaction(reference.record)
    left, middle, right = reference.record.mapped_reaction_smiles.split(">")
    duplicated = reference.record.model_copy(
        update={"mapped_reaction_smiles": f"{left}>{middle}>{right}.{right}"}
    )
    projected = project_changes(
        duplicated, reference.material, reference.witnesses[0], analysis, target=target
    )
    assert projected["formed_target_bonds"] == []
    assert not has_region_method(projected)
    assert projected["region_consensus"]["state"] == "unresolved"


def test_full_search_promotes_region_method_and_merges_later_witness(
    tmp_path, request_factory, monkeypatch
):
    """同材料后续查询得到区域共识时应升级方法贡献，不能永远保留首次未知标签。"""
    target, reference, smiles = bridge_case()
    parent = next(
        f
        for f in initial_families(target)
        if f.rule_id == "complete_ring_system" and len(f.target_atoms) == 7
    )
    families = [parent, parent.model_copy(update={"id": "second-core-query"})]
    module = import_module("reaction_reference.application.search")
    monkeypatch.setattr(module, "initial_families", lambda *_: families)
    original = module.project_changes
    calls = []

    def first_unknown(*args, **kwargs):
        """首次只给未知，第二个实际查询仍执行正式投影，验证后续合并升级路径。"""
        calls.append(True)
        if len(calls) == 1:
            return {"formed_target_bonds": [], "changed_target_atoms": [], "support": "unknown"}
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "project_changes", first_unknown)
    path = tmp_path / "bridge.jsonl"
    path.write_text(reference.record.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                smiles,
                options={
                    "include_proposals": False,
                    "include_usage": False,
                    "directed_followups": False,
                },
                budget={"max_tasks": 100},
            ),
            source,
        )
    finally:
        source.close()
    assert len(calls) >= 2
    assert package.displayed_reference_ids
    result = next(r for r in package.results if r.id in package.displayed_reference_ids)
    assert result.contribution == "local_method"
    assert has_region_method(result.coverage["projected_changes"])
    assert result.coverage["projected_changes"]["formed_target_bonds"] == []
    assert not result.obtainment_hit
