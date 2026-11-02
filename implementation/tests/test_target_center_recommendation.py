"""真实七条苯甲酰胺结果回归：目标反应中心过滤、连接端迁移排序和宽查询限制。"""

import json
from pathlib import Path

import pytest
from rdkit import Chem

from reaction_reference.adapters.sources import JsonlSource
from reaction_reference.application.search import search
from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import Reference
from reaction_reference.ranking.engine import rank_references
from reaction_reference.retrieval.planner import initial_families, plan_families


def saved_references():
    """加载用户实际看到的七条候选，不依赖实时数据库变化和查询超时。"""
    payload = json.loads(
        (Path(__file__).parent / "fixtures/target_center_ranking.json").read_text()
    )
    return payload["target_smiles"], [
        Reference.model_validate_json(json.dumps(r)) for r in payload["references"]
    ]


def test_actual_candidates_follow_target_method_order_and_filter_usage():
    """先重新执行家族匹配排除无关杂环，再验证用户期望的1、4、3、7方法顺序。"""
    smiles, references = saved_references()
    target = parse(smiles)
    families = initial_families(target)
    eligible = [
        r
        for r in references
        if any(
            match_family(f, parse(r.material.smiles), target, r.material.instance_id).state
            == "match"
            for f in families
        )
    ]
    assert not any(r.record.source.record_id == "4381854" for r in eligible)
    for items in (eligible, list(reversed(eligible))):
        ranked, displayed = rank_references(items, target_smiles=smiles)
        by_id = {r.id: r for r in ranked}
        assert [by_id[i].record.source.record_id for i in displayed] == [
            "2174992",
            "669207",
            "1119512",
            "4793635",
        ]
        for identifier in ("2928670", "669208"):
            excluded = next(r for r in ranked if r.record.source.record_id == identifier)
            assert excluded.display_position is None
            assert (
                "recommendation_excluded:input_usage_without_target_product_transformation"
                in excluded.reasons
            )
        assert not any(r.obtainment_hit for r in ranked)


def test_outside_and_unknown_centers_keep_distinct_exclusion_reasons():
    """产物侧目标外变化与映射未知分别留痕，不谎称未知记录已被证明无关。"""
    smiles, references = saved_references()
    method = next(r for r in references if r.record.source.record_id == "2174992")
    for support, reason in (
        ("single_mapping_inference", "reaction_center_outside_target"),
        ("ambiguous_product_mapping", "target_reaction_center_unresolved"),
    ):
        candidate = method.model_copy(
            update={
                "contribution": "structure_clue",
                "coverage": {
                    **method.coverage,
                    "projected_changes": {
                        "formed_target_bonds": [],
                        "changed_target_atoms": [],
                        "support": support,
                    },
                },
            }
        )
        ranked, displayed = rank_references([candidate], target_smiles=smiles)
        assert not displayed
        assert ranked[0].display_position is None
        assert "recommendation_excluded:" + reason in ranked[0].reasons
    exact = candidate.model_copy(update={"target_requirements_satisfied": True})
    ranked, displayed = rank_references([exact], target_smiles=smiles)
    assert displayed == [exact.id]
    assert not ranked[0].obtainment_hit


@pytest.mark.parametrize("smiles", ["CCN(C)C(=O)c1ccccc1", "Cc1ccccc1", "c1ccc(CCc2ccccc2)cc1"])
def test_no_standalone_benzene_in_large_target(smiles):
    """多种目标和大查询预算都不应绕过规则，重新生成裸苯环查询。"""
    families = plan_families(parse(smiles), max_families=100)
    for family in families:
        query = Chem.MolFromSmarts(family.core_smarts)
        assert not (
            query.GetNumAtoms() == 6
            and all(a.GetIsAromatic() and a.GetAtomicNum() == 6 for a in query.GetAtoms())
        )


@pytest.mark.parametrize("smiles", ["c1ccccc1", "Cc1ccncc1", "Cc1ccc2ccccc2c1"])
def test_complete_target_and_distinctive_ring_cores_remain(smiles):
    """完整苯目标、杂芳环和稠合芳环保持可检索，不泛化成禁止所有环查询。"""
    families = initial_families(parse(smiles))
    assert any(f.rule_id == "complete_ring_system" for f in families)


def test_saved_reactions_are_reanalyzed_and_filtered_end_to_end(tmp_path, request_factory):
    """重新分析七条实际反应，不依赖冻结贡献标签，覆盖两侧材料的无关反应中心。"""
    smiles, references = saved_references()
    path = tmp_path / "reactions.jsonl"
    path.write_text("\n".join(r.record.model_dump_json() for r in references))
    source = JsonlSource(path, exhaustive=True)
    try:
        package = search(
            request_factory(
                smiles,
                options={"include_proposals": False, "include_usage": True},
                budget={"max_tasks": 160},
            ),
            source,
        )
    finally:
        source.close()
    by_id = {r.id: r for r in package.results}
    assert [by_id[i].record.source.record_id for i in package.displayed_reference_ids] == [
        "2174992",
        "669207",
        "1119512",
        "4793635",
    ]
    assert not any(r.record.source.record_id == "4381854" for r in package.results)
    for identifier in ("2928670", "669208"):
        rejected = [r for r in package.results if r.record.source.record_id == identifier]
        assert rejected
        assert all(r.display_position is None for r in rejected)
        assert all(
            any(s.startswith("recommendation_excluded:") for s in r.reasons) for r in rejected
        )
