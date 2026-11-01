"""源端必要条件编译：单端口精确支链提前预筛，完整Markush仍决定最终匹配。"""

import pytest
from rdkit import Chem

from reaction_reference.chemistry.markush import candidate_smarts, match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.domain.models import QueryFamily, RConstraint
from reaction_reference.retrieval.planner import _core_smarts, directed_family, functional_matches


@pytest.mark.parametrize(
    "smiles",
    [
        "CCc1ncc(CCC)cc1",
        "COC(=O)c1ccc(C#N)cc1",
        "C[C@H](O)c1ccccc1",
        "O=C(O)c1ccc([13CH3])cc1",
        "C/C=C/c1ccccc1",
        "C1CCC(CC)CC1",
    ],
)
def test_real_exact_r_hits_survive_source_necessary_query(smiles):
    """芳基酯、腈、立体、同位素和烯烃的真实精确支链命中必须通过源端必要条件。"""
    target = parse(smiles)
    core = set(target.GetRingInfo().AtomRings()[0])
    smarts, ids = _core_smarts(target, core, functional_matches(target))
    parent = QueryFamily(
        id="core",
        layer="core",
        core_smarts=smarts,
        target_atoms=ids,
        rule_id="test",
        rule_version="test",
        description="真实支链测试",
    )
    child = directed_family(parent, target, set(range(len(ids))))
    assert match_family(child, target, target, "self").state == "match"
    assert target.HasSubstructMatch(Chem.MolFromSmarts(candidate_smarts(child)), useChirality=True)


def test_prefilter_rejects_absent_attachment_but_does_not_replace_exact_r():
    """缺氧候选在预筛排除，带额外取代的醇仍可进入预筛，但精确R核验会拒绝。"""
    family = QueryFamily(
        id="carbon",
        layer="core",
        core_smarts="[#6]",
        target_atoms=[0],
        rule_id="test",
        rule_version="test",
        description="甲醇",
        r_constraints=[RConstraint(position=0, exact_fragment="O[*:1]", requirement="required")],
    )
    query = Chem.MolFromSmarts(candidate_smarts(family))
    assert not parse("CCN").HasSubstructMatch(query)
    assert parse("COC").HasSubstructMatch(query)
    assert match_family(family, parse("COC"), parse("CO"), "ether").state == "no_match"


@pytest.mark.parametrize("fragment", ["C([*:1])[*:2]", "C[*:2]", "CO", "O.[*:1]"])
def test_unproven_port_semantics_fall_back_to_core(fragment):
    """多端口、错误端口、无端口和多组分不能拼出过严的伪预筛。"""
    family = QueryFamily(
        id="fallback",
        layer="core",
        core_smarts="[#6]",
        target_atoms=[0],
        rule_id="test",
        rule_version="test",
        description="保守回退",
        r_constraints=[RConstraint(position=0, exact_fragment=fragment, requirement="required")],
    )
    assert candidate_smarts(family) == family.core_smarts


def test_repeated_required_branches_preserve_multiplicity():
    """两个相同必需R块必须增加两份原子，不能只编译一次。"""
    constraint = RConstraint(position=0, exact_fragment="C[*:1]", requirement="required")
    family = QueryFamily(
        id="twice",
        layer="core",
        core_smarts="[#6]",
        target_atoms=[0],
        rule_id="test",
        rule_version="test",
        description="两条甲基",
        r_constraints=[constraint, constraint],
    )
    query = Chem.MolFromSmarts(candidate_smarts(family))
    assert query.GetNumAtoms() == 3
    assert not parse("CC").HasSubstructMatch(query)
    assert parse("CCC").HasSubstructMatch(query)
