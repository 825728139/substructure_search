"""关键支链组合查询：核对真实连接位置、整体功能单元与组合数量边界。"""

import pytest

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import QueryFamily
from reaction_reference.retrieval.planner import (
    _attachment_seeds,
    _core_smarts,
    functional_matches,
    initial_families,
    plan_families,
)


def test_two_substituent_query_preserves_relative_positions():
    """同时保留芳基酯与腈时不能把邻位异构体当作对位先例。"""
    target = parse("COC(=O)c1ccc(C#N)cc1")
    core = {a.GetIdx() for a in target.GetAtoms() if a.GetIsAromatic()}
    groups = functional_matches(target)
    atoms, rule = next(
        seed for seed in _attachment_seeds(target, core, groups) if seed[1].endswith(":2")
    )
    smarts, ids = _core_smarts(target, atoms, groups)
    family = QueryFamily(
        id="pair",
        layer="core",
        core_smarts=smarts,
        target_atoms=ids,
        rule_id=rule,
        rule_version="test",
        description="保留酯和腈相对位置",
    )
    assert match_family(family, target, target, "self").state == "match"
    assert match_family(family, parse("COC(=O)c1ccccc1C#N"), target, "ortho").state == "no_match"


def test_attachment_combinations_have_bounded_unique_connected_queries():
    """支链组合有数量上限且全部属于目标连通子图，不能生成不存在的拼接结构。"""
    from rdkit import Chem

    target = parse("CC1C(C)C(C)C(C)C(C)C1C")
    core = set(target.GetRingInfo().AtomRings()[0])
    seeds = _attachment_seeds(target, core, functional_matches(target), limit=5)
    assert len(seeds) == 5
    assert len({tuple(sorted(atoms)) for atoms, _ in seeds}) == 5
    for atoms, _ in seeds:
        smarts, _ = _core_smarts(target, atoms, [])
        query = Chem.MolFromSmarts(smarts)
        assert len(Chem.GetMolFrags(query)) == 1
        assert target.HasSubstructMatch(query)


def test_public_planner_includes_attachment_query_and_keeps_bare_core():
    """正式规划入口同时保留裸骨架和带关键支链组合，仍遵循家族总数上限。"""
    families = plan_families(parse("COC(=O)c1ccc(C#N)cc1"), max_families=12)
    assert len(families) <= 12
    assert any(f.rule_id == "complete_ring_system" for f in families)
    assert any(f.rule_id == "core_attachment_combination:2" for f in families)


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("c1ccccc1NCCO", "match"),
        ("Cc1ccc(NCCO)cc1", "match"),
        ("c1ccccc1N(C)CCO", "no_match"),
        ("c1ccccc1OCCO", "no_match"),
    ],
)
def test_attachment_environment_relaxes_tail_but_preserves_nitrogen_role(candidate, expected):
    """远端烷链可变且核心仍可加取代，但连接端仲胺不能静默变成叔胺或醚。"""
    target = parse("c1ccccc1NCCCCC")
    family = next(
        f for f in plan_families(target, 30) if f.rule_id == "core_attachment_environment:1"
    )
    assert match_family(family, parse(candidate), target, "local").state == expected


def test_attachment_environment_closes_functional_units_and_rings():
    """酰胺邻域保持C=O与N，苄基连接邻域保留完整苯环而放开对位远端烷链。"""
    from rdkit import Chem

    for smiles, required in [
        ("c1ccccc1C(=O)NCCCCC", "C(=O)N"),
        ("C1CCCCC1Cc1ccc(CCCCC)cc1", "Cc1ccccc1"),
    ]:
        target = parse(smiles)
        family = next(
            f for f in plan_families(target, 30) if f.rule_id == "core_attachment_environment:1"
        )
        atoms = set(family.target_atoms)
        assert any(
            set(match) <= atoms
            for match in target.GetSubstructMatches(Chem.MolFromSmarts(required))
        )
        assert match_family(family, target, target, "self").state == "match"
        assert len(atoms) < target.GetNumHeavyAtoms()


def test_single_and_pair_questions_precede_repeated_tail_precision():
    """两条长支链都有局部/完整版本时，第二个名额应查询双位点而不是重复单支链。"""
    target = parse("CCCCCNc1ccc(NCCCCC)cc1")
    core = {a.GetIdx() for a in target.GetAtoms() if a.GetIsAromatic()}
    seeds = _attachment_seeds(target, core, functional_matches(target), limit=2)
    assert [rule for _, rule in seeds] == [
        "core_attachment_environment:1",
        "core_attachment_environment:2",
    ]
    assert seeds[0][0] < seeds[1][0]


@pytest.mark.parametrize(
    "smiles",
    [
        "CCCCCNc1ccc(OCCCCC)cc1",
        "COC(=O)C1CC(NCCCCC)C1",
        "CCN1CCC(C(=O)NCCCCC)CC1",
    ],
)
def test_default_plan_includes_pair_and_preserves_full_alternatives(smiles):
    """默认计划提供双位点查询，较大预算仍保留完整远端版本和裸核心。"""
    target = parse(smiles)
    families = initial_families(target)
    core = [f for f in families if f.layer == "core"]
    assert core[0].rule_id == "complete_ring_system"
    assert any(f.rule_id.endswith(":2") for f in core)
    expanded = plan_families(target, 48)
    assert any(f.rule_id == "core_attachment_combination:2" for f in expanded)
    assert len({f.id for f in expanded}) == len(expanded)
