"""等价原子排序的查询稳定性，以及官能团补齐与原始目标编号的正确性。"""

import random

import pytest
from rdkit import Chem

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.retrieval.planner import _close_units, functional_matches, initial_families


def query_signature(family):
    """去掉仅用于目标定位的映射号，比较同一查询的结构语义与选择顺序。"""
    query = Chem.MolFromSmarts(family.core_smarts)
    for atom in query.GetAtoms():
        atom.SetAtomMapNum(0)
    return family.layer, family.rule_id, Chem.MolToSmarts(query)


@pytest.mark.parametrize(
    "smiles",
    [
        "CCCCN1C(=O)c2cccc3c(NN)ccc(c23)C1=O",
        "Cc1ccc(-c2cc(C)nn2-c2ccc(S(N)(=O)=O)cc2)cc1",
        "[13CH3][C@@H](O)C(=O)Nc1ccc(C#N)cc1",
        "OCCC(CO)(CN)CCO",
        "C1CC2CCC1C2c1ccccc1",
        "c1ccc(CCc2ccccc2)cc1",
    ],
)
def test_equivalent_atom_orders_keep_query_selection_and_correct_correspondence(smiles):
    """反转和固定随机重排不改变非精确家族选择；每个查询仍精确回指当前输入编号。"""
    target = parse(smiles, target=True)
    baseline = [query_signature(f) for f in initial_families(target) if f.relation != "strict"]
    orders = [list(reversed(range(target.GetNumAtoms())))]
    for seed in range(3):
        order = list(range(target.GetNumAtoms()))
        random.Random(seed).shuffle(order)
        orders.append(order)
    for order in orders:
        reordered = Chem.RenumberAtoms(target, order)
        families = initial_families(reordered)
        assert [query_signature(f) for f in families if f.relation != "strict"] == baseline
        for family in families:
            query = Chem.MolFromSmarts(family.core_smarts)
            assert [a.GetAtomMapNum() - 1 for a in query.GetAtoms()] == family.target_atoms
            assert match_family(family, reordered, reordered, "self").state == "match"
        assert Chem.MolToSmiles(reordered) == Chem.MolToSmiles(target)


def test_functional_closure_does_not_depend_on_group_enumeration_order():
    """芳位连接的N—N单元需要稳定补齐，不能因两个胺匹配顺序而漏掉末端N。"""
    target = parse("NNc1ccccc1")
    groups = functional_matches(target)
    aromatic = {a.GetIdx() for a in target.GetAtoms() if a.GetIsAromatic()}
    forward = _close_units(aromatic, groups, target, adjacent=True)
    backward = _close_units(aromatic, list(reversed(groups)), target, adjacent=True)
    assert forward == backward == set(range(target.GetNumAtoms()))
