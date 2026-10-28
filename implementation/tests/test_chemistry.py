import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError
from rdkit import Chem

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import canonical, meets_target, outside_blocks, parse
from reaction_reference.domain.models import QueryFamily, RConstraint, SearchRequest
from reaction_reference.retrieval.planner import plan_families


def family(smarts, target_atoms, **kwargs):
    return QueryFamily(
        id="test",
        layer="core",
        core_smarts=smarts,
        target_atoms=target_atoms,
        rule_id="test",
        rule_version="1",
        description="test",
        **kwargs,
    )


@pytest.mark.parametrize(
    "s", ["CCO", "CCNC(=O)c1ccccc1", "C1CCCO1", "CC(=O)NCCO", "C", "[13CH3]CO", "C[C@H](O)CC"]
)
def test_auto_queries_preserve_target(s):
    target = parse(s, target=True)
    families = plan_families(target)
    assert {f.layer for f in families} == {"whole", "core", "fragment"}
    for f in families:
        result = match_family(f, target, target, "self", max_mappings=2048)
        assert result.state == "match", (s, f, result)
        assert max(w.target_atom_coverage for w in result.witnesses) == 1


def test_functional_oxygen_role_is_preserved():
    target = parse("CCO")
    f = plan_families(target)[0]
    assert match_family(f, parse("CCOC"), target, "ether").state == "no_match"


def test_whole_r_not_just_first_atom():
    target = parse("CO")
    f = family(
        "[O]",
        [1],
        r_constraints=[
            RConstraint(position=0, requirement="required", category="alkyl", max_carbons=2)
        ],
    )
    assert match_family(f, parse("CCO"), target, "alkyl").state == "match"
    assert match_family(f, parse("OCCN"), target, "has_N").state == "no_match"
    assert match_family(f, parse("OCCC"), target, "too_long").state == "no_match"
    assert match_family(f, parse("Oc1ccccc1"), target, "aryl").state == "no_match"


def test_symmetric_core_checks_all_orientations_before_dedup():
    target = parse("CCO")
    f = family(
        "[C][C]",
        [0, 1],
        r_constraints=[
            RConstraint(position=0, requirement="required"),
            RConstraint(position=1, requirement="hydrogen"),
        ],
    )
    result = match_family(f, parse("CCO"), target, "reverse")
    assert result.state == "match"
    assert result.witnesses[0].core_source_atoms == [1, 0]
    limited = match_family(f, parse("CCO"), target, "reverse", max_mappings=1)
    assert limited.state == "unknown"
    assert not limited.enumeration_complete


def test_extra_internal_edge_is_not_a_chain_witness():
    target = parse("CCC")
    assert (
        match_family(family("[C][C][C]", [0, 1, 2]), parse("C1CC1"), target, "cycle").state
        == "no_match"
    )


def test_explicit_deuterium_is_not_heavy_sidechain():
    mol = parse("[2H]C(O)C")
    blocks = outside_blocks(mol, [1, 2, 3])
    assert not blocks
    assert not meets_target(parse("CCO"), parse("[2H]C(O)C"))


def test_target_stereo_is_a_requirement():
    target = parse("C[C@H](O)CC")
    assert meets_target(target, target)
    assert not meets_target(parse("C[C@@H](O)CC"), target)
    assert not meets_target(parse("CCC(O)C"), target)
    assert meets_target(target, parse("CCC(O)C"))


def test_equality_checks_entire_substituents():
    target = parse("CCOCC")
    f = family("[C][O][C]", [1, 2, 3], equal_r_positions=[[0, 2]])
    assert match_family(f, target, target, "equal").state == "match"
    assert match_family(f, parse("CCOCCC"), target, "unequal").state == "no_match"


@given(st.sampled_from(["CCO", "CCN", "CCNC(=O)c1ccccc1"]), st.integers(min_value=0, max_value=10))
def test_atom_order_does_not_change_canonical_identity(smiles, shift):
    mol = parse(smiles)
    order = list(range(mol.GetNumAtoms()))
    shift %= len(order)
    reordered = Chem.RenumberAtoms(mol, order[shift:] + order[:shift])
    assert canonical(reordered) == canonical(mol)
    assert meets_target(reordered, mol)


def test_input_validation_rejects_unknown_and_coerced_budget():
    with pytest.raises(ValidationError):
        SearchRequest(target={"value": "CCO"}, budget={"max_tasks": True})
    with pytest.raises(ValidationError):
        SearchRequest(target={"value": "CCO"}, options={"include_usage": "false"})
    with pytest.raises(ValidationError):
        SearchRequest(target={"value": "CCO"}, paid_plan="pro")


def test_isotopic_hydrogen_is_retained_in_core_and_r_signature():
    from reaction_reference.chemistry.structures import fragment_key
    from reaction_reference.retrieval.planner import _core_smarts

    target = parse("[2H]C(O)C")
    smarts, atoms = _core_smarts(target, [1, 2, 3], [])
    f = family(smarts, atoms)
    assert match_family(f, target, target, "D").state == "match"
    assert match_family(f, parse("CCO"), target, "H").state == "no_match"
    assert fragment_key(target, [1, 3], {2: 0}) != fragment_key(parse("CCO"), [0, 1], {2: 0})


def test_native_generic_query_restores_properties_after_ir_roundtrip():
    f = family("OC* |$;;ARY$|", [0, 1, 2])
    restored = type(f).model_validate_json(f.model_dump_json())
    target = parse("OCc1ccccc1")
    assert match_family(restored, target, target, "aryl").state == "match"
    assert match_family(restored, parse("OCC1CCCCC1"), target, "cycloalkyl").state == "no_match"


def test_sitewise_union_is_not_joint_coverage():
    from reaction_reference.chemistry.markush import coverage_summary
    from reaction_reference.retrieval.planner import _core_smarts

    target = parse("COc1ccc(OC)cc1")
    ring = list(target.GetRingInfo().AtomRings()[0])
    smarts, ids = _core_smarts(target, ring, [])
    f = family(smarts, ids)
    result = match_family(f, parse("COc1ccccc1"), target, "one-branch", max_mappings=2048)
    coverage = coverage_summary(result.witnesses, target, result.enumeration_complete)
    assert coverage["sitewise_union_atom_coverage"] == 1
    assert coverage["joint_witness"]["atom_coverage"] < 1
    assert not coverage["best_found_is_proven_maximum"]
