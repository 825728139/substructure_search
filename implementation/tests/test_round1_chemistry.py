"""第一轮复审：支链精确约束中的双键、四面体手性与氢表示一致性。"""

import pytest
from rdkit import Chem

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import outside_blocks, parse
from reaction_reference.domain.models import QueryFamily
from reaction_reference.retrieval.planner import _core_smarts, directed_family


def ring_family(molecule):
    """用完整苯环构造核心，并固定目标所有外围支链。"""
    core = list(molecule.GetRingInfo().AtomRings()[0])
    smarts, atoms = _core_smarts(molecule, core, [])
    parent = QueryFamily(
        id="ring",
        layer="core",
        core_smarts=smarts,
        target_atoms=atoms,
        rule_id="regression",
        rule_version="1",
        description="精确外围支链",
    )
    return directed_family(parent, molecule, range(len(core)))


@pytest.mark.parametrize("other", ["c1ccccc1/C=C\\C", "c1ccccc1C=CC"])
def test_exact_r_preserves_double_bond_requirements(other):
    """精确支链要求指定双键构型时，反构型或未指定构型不能混入。"""
    target = parse("c1ccccc1/C=C/C")
    family = ring_family(target)
    assert match_family(family, target, target, "same").state == "match"
    assert match_family(family, parse(other), target, "other").state == "no_match"


@pytest.mark.parametrize(
    "smiles", ["c1ccccc1[C@H](F)CC", "c1ccccc1/C=C/C", "c1ccccc1/C=C\\C", "c1ccccc1[C@]([2H])(F)CC"]
)
def test_r_stereo_signature_is_invariant_to_hydrogens_and_atom_order(smiles):
    """加显式氢或改变局部原子编号后，同一支链的立体签名应保持一致。"""
    target = parse(smiles)
    core = list(target.GetRingInfo().AtomRings()[0])
    expected = outside_blocks(target, core)[0]["fragment"]
    expanded = Chem.AddHs(target)
    for molecule in (target, expanded):
        assert outside_blocks(molecule, core)[0]["fragment"] == expected
        order = list(reversed(range(molecule.GetNumAtoms())))
        inverse = {old: new for new, old in enumerate(order)}
        reordered = Chem.RenumberAtoms(molecule, order)
        assert outside_blocks(reordered, [inverse[i] for i in core])[0]["fragment"] == expected


def test_exact_chiral_r_accepts_explicit_hydrogen_view():
    """精确四面体支链在显式氢视图下仍应匹配原目标，反构型仍被排除。"""
    target = parse("c1ccccc1[C@H](F)CC")
    family = ring_family(target)
    assert match_family(family, Chem.AddHs(target), target, "explicit").state == "match"
    opposite = Chem.AddHs(parse("c1ccccc1[C@@H](F)CC"))
    assert match_family(family, opposite, target, "opposite").state == "no_match"
