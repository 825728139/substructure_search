"""回归测试：实际反应变化、观察证据与单输入回放。"""

import pytest

from reaction_reference.analogs.transfer import generate_proposals
from reaction_reference.application.budget import Budget
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import BudgetConfig, Material, Observation, Reference
from reaction_reference.evidence.claims import evidence_for
from reaction_reference.reaction_analysis.analyze import analyze_reaction


def analysis(amide, mapped):
    """用给定映射式重建测试两侧材料，再调用实际分析，隔离端点归属与键变化场景。"""
    materials = []
    if mapped.count(">") == 2:
        left, _agents, right = mapped.split(">")
        for role, side in [("reactant", left), ("product", right)]:
            for i, text in enumerate(side.split(".")):
                materials.append(Material(instance_id=f"{role}:{i}", role=role, smiles=text))
    return analyze_reaction(
        amide.model_copy(update={"mapped_reaction_smiles": mapped, "materials": materials})
    )


def test_connection_and_leaving_fragment_not_all_broken(amide):
    """确认酰胺新键与离去边界正确分账，缺少副产物不导致虚构大量断键。"""
    a = analyze_reaction(amide)
    assert a.state == "analyzed"
    assert [c.maps for c in a.formed] == [(1, 3)]
    assert a.detached_boundaries == [(1, 12)]
    assert not a.broken
    assert "acyl_C_N_connection" in a.reaction_classes


@pytest.mark.parametrize(
    "mapped, reason",
    [
        ("[CH3:1][OH:1]>>[CH2:1]=[O:2]", "duplicate_positive_atom_maps"),
        ("[CH3:1][OH:2]>>[13CH2:1]=[O:2]", "mapping_element_isotope_or_source_conflict"),
        ("CCO", "invalid_mapped_reaction"),
    ],
)
def test_invalid_mapping_is_unknown(amide, mapped, reason):
    """确认重复正映射、同位素冲突或非法反应式明确返回未知及原因。"""
    a = analysis(amide, mapped)
    assert a.state == "unknown" and reason in a.reasons


def test_map_zero_never_establishes_cross_side_identity(amide):
    """确认 map=0 原子不参与跨侧身份，不从未映射区域制造成断键。"""
    a = analysis(amide, "CC[OH:1]>>CC[OH:1]")
    assert a.state == "partial"
    assert not a.formed and not a.broken


def test_resonance_swap_not_transformation(amide):
    """确认限定硝基氧共振交换记为表示变化，不计真实键级转化。"""
    a = analysis(amide, "[CH3:1][N+:2](=[O:3])[O-:4]>>[CH3:1][N+:2]([O-:3])=[O:4]")
    assert len(a.representation_only) == 2
    assert not a.order_changed


def test_real_proton_transfer_not_suppressed_as_resonance(amide):
    """确认羧酸的实际 H 迁移不会被共振规则抹除。"""
    a = analysis(amide, "[CH3:1][C:2](=[O:3])[OH:4]>>[CH3:1][C:2]([OH:3])=[O:4]")
    assert len(a.order_changed) == 2
    assert not a.representation_only


def test_observed_ring_changes(source):
    """确认从实际命中反应变化识别闭环和开环，不依赖检索前虚构切环位置。"""
    for rid, expected in [
        ("demo-ring-closure", "ring_closure"),
        ("demo-ring-opening", "ring_opening"),
    ]:
        a = analyze_reaction(next(r for r in source.records if r.id == rid))
        assert expected in a.topology


def test_synthetic_sources_never_become_literature(amide):
    """确认合成示例有演示 Claim，但没有真实制备/获得/使用命中。"""
    product = amide.materials[-1]
    prep, obtained, used, claims = evidence_for(amide, product)
    assert not any([prep, obtained, used])
    assert claims[0].support == "synthetic_illustration"


def test_product_presence_alone_not_preparation(amide):
    """确认有产品结构不等于制得，实际输入使用只归属于对应反应物。"""
    actual_source = amide.source.model_copy(update={"synthetic": False})
    record = amide.model_copy(update={"source": actual_source, "observations": []})
    assert evidence_for(record, record.materials[-1])[:3] == (False, False, False)
    assert evidence_for(record, record.materials[0])[:3] == (False, False, True)


def test_conflict_cancels_positive_outcome(amide):
    """确认同产品的明确冲突会取消阳性制备标记。"""
    actual_source = amide.source.model_copy(update={"synthetic": False})
    conflict = Observation(
        product_instance_id=amide.materials[-1].instance_id,
        result="conflict",
        evidence_text="conflicting report",
        source_location="test",
    )
    record = amide.model_copy(
        update={"source": actual_source, "observations": amide.observations + [conflict]}
    )
    assert not evidence_for(record, record.materials[-1])[0]


def reference(amide):
    """为回放测试构造带来源映射分析的最小 Reference。"""
    return Reference(
        id="ref",
        record=amide,
        material=amide.materials[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=analyze_reaction(amide),
        molecular_weight=149,
    )


def test_single_reactant_change_core_or_branch(amide):
    """确认支链或母核差异都能在来源自回放后仅替换一个输入，并满足完整目标。"""
    ref = reference(amide)
    for target, expected_slot in [("CCCNC(=O)c1ccccc1", 1), ("CCNC(=O)c1ccc(F)cc1", 0)]:
        proposals, reason = generate_proposals(ref, parse(target), Budget(BudgetConfig()))
        assert proposals, reason
        p = proposals[0]
        assert p.replaced_slot == expected_slot and p.target_found
        assert (
            sum(a != b for a, b in zip(p.original_reactants, p.proposed_reactants, strict=False))
            == 1
        )
        assert p.proposal_not_observed
        assert "synthetic_source_illustration_not_literature" in p.limitations


def test_two_changes_and_unassigned_step_do_not_transfer(amide):
    """确认需要同时改两个输入或来源未明确分步时不自动给出单输入迁移。"""
    ref = reference(amide)
    proposals, _ = generate_proposals(ref, parse("CCCNC(=O)c1ccc(F)cc1"), Budget(BudgetConfig()))
    assert not proposals
    ref = ref.model_copy(
        update={"record": amide.model_copy(update={"event_scope": "source_record_net"})}
    )
    proposals, reason = generate_proposals(ref, parse("CCCNC(=O)c1ccccc1"), Budget(BudgetConfig()))
    assert not proposals and reason == "source_step_not_assigned"


def test_source_endpoint_conflict_is_not_a_validated_mapping(amide):
    """确认映射端点不属于记录实际材料时不能作为已校验反应分析。"""
    changed = amide.model_copy(update={"mapped_reaction_smiles": "[CH3:1][OH:2]>>[CH2:1]=[O:2]"})
    a = analyze_reaction(changed)
    assert a.state == "unknown"
    assert "mapped_endpoints_do_not_reconcile_with_material_instances" in a.reasons


def test_source_radius2_template_can_transfer_a_non_registry_reaction(amide):
    """确认合法来源 radius-2 模板经自回放可生成注册酰胺规则以外的单输入建议。"""
    mats = [
        Material(instance_id="r1", role="reactant", smiles="CCBr", actual_input=True),
        Material(instance_id="r2", role="reactant", smiles="Oc1ccccc1", actual_input=True),
        Material(instance_id="p", role="product", smiles="CCOc1ccccc1"),
    ]
    record = amide.model_copy(
        update={
            "id": "synthetic-ether",
            "materials": mats,
            "observations": [
                Observation(
                    product_instance_id="p",
                    result="reported_prepared",
                    evidence_text="Synthetic software case, no experiment",
                    source_location="test",
                )
            ],
            "mapped_reaction_smiles": "[CH3:1][CH2:2][Br:3].[OH:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1>>[CH3:1][CH2:2][O:4][c:5]1[cH:6][cH:7][cH:8][cH:9][cH:10]1",
            "retro_template": "[C:1]-[C:2]-[O;H0:4]-[c:5]>>[C:1]-[C:2]-Br.[OH:4]-[c:5]",
        }
    )
    ref = Reference(
        id="ether",
        record=record,
        material=mats[-1],
        family_ids=[],
        layers=["whole"],
        witnesses=[],
        analysis=analyze_reaction(record),
        molecular_weight=122,
    )
    proposals, reason = generate_proposals(ref, parse("CCCOc1ccccc1"), Budget(BudgetConfig()))
    assert proposals, reason
    assert proposals[0].rule_id.startswith("source_radius2_retro:")
    assert proposals[0].target_found


def test_replay_retains_product_sets_and_independent_enumeration_limit():
    """确认回放保留整组产品，并把结构有效和枚举截断分开。"""
    from rdkit.Chem import rdChemReactions

    from reaction_reference.analogs.transfer import replay

    reaction = rdChemReactions.ReactionFromSmarts("[C:1]>>[C:1].O")
    groups, complete, valid = replay(reaction, [parse("CCCC")], max_sets=2)
    assert len(groups) == 2 and all(len(g) == 2 for g in groups)
    assert not complete and valid
