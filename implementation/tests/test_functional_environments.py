"""局部官能团连接环境：允许远端和环大小变化，保留氢数、键型与环内外角色。"""

import pytest

from reaction_reference.chemistry.markush import match_family
from reaction_reference.chemistry.structures import parse
from reaction_reference.retrieval.planner import initial_families


@pytest.mark.parametrize(
    "target,positive,negative,group",
    [
        ("CCCCCCNC(=O)CCCCC", "CCNC(=O)CC", "CCN(C)C(=O)CC", "amide"),
        ("CCCCCCCN", "CCCN", "CCN(C)C", "amine"),
        ("O=C1NCCCCCC1", "O=C1NCCCCC1", "CCC(=O)NCCC", "amide"),
        ("CCCCOCCCC", "CCOCC", "CCOC(=O)CC", "ether"),
    ],
)
def test_default_local_environment_preserves_chemical_role(target, positive, negative, group):
    """默认计划存在接受局部等价正例、拒绝官能团角色不同反例的家族。"""
    molecule = parse(target)
    families = [
        f
        for f in initial_families(molecule)
        if f.rule_id == f"functional_connection_environment:{group}"
    ]
    assert families
    assert any(
        match_family(f, parse(positive), molecule, "positive").state == "match"
        and match_family(f, parse(negative), molecule, "negative").state == "no_match"
        for f in families
    )
    assert all(match_family(f, molecule, molecule, "self").state == "match" for f in families)


def test_local_ring_environment_does_not_claim_full_ring_identity():
    """不同环大小可作局部参考，但局部查询不覆盖完整目标，也不抹去完整环系查询。"""
    target = parse("O=C1NCCCCCC1")
    source = parse("O=C1NCCCCC1")
    families = initial_families(target)
    local = next(f for f in families if f.rule_id == "functional_connection_environment:amide")
    result = match_family(local, source, target, "different-ring")
    assert result.state == "match"
    assert all(w.target_atom_coverage < 1 for w in result.witnesses)
    full = next(f for f in families if f.rule_id == "complete_ring_system")
    assert match_family(full, source, target, "different-ring").state == "no_match"


def test_empty_local_near_pool_does_not_jump_ahead_of_other_family(
    tmp_path, request_factory, monkeypatch, amide
):
    """空局部近邻的独立补查保持队尾，其他核心先执行；补查本身仍保留。"""
    from importlib import import_module

    from reaction_reference.adapters.sources import JsonlSource
    from reaction_reference.ports.sources import CandidatePage

    smiles = next(m.smiles for m in amide.materials if m.role == "product")
    families = initial_families(parse(smiles))
    local = next(f for f in families if f.rule_id.startswith("functional_connection_environment:"))
    other = next(f for f in families if f.relation == "strict")
    module = import_module("reaction_reference.application.search")
    monkeypatch.setattr(module, "initial_families", lambda *_: [local, other])
    path = tmp_path / "source.jsonl"
    path.write_text(amide.model_dump_json() + "\n")
    source = JsonlSource(path, exhaustive=True)
    source.max_selection_stage = 1
    source.fragment_selection_stages = True
    calls = []
    original = source.candidate_page

    def page(family, role, cursor, limit, target, stage=0):
        """只模拟局部初选为空，其余候选仍来自真实样本结构。"""
        calls.append((family.id, stage))
        if family.id == local.id and stage == 0:
            return CandidatePage([], None, True, True, "near_pool")
        return original(family, role, cursor, limit, target, stage)

    monkeypatch.setattr(source, "candidate_page", page)
    try:
        package = module.search(
            request_factory(
                smiles,
                options={
                    "include_usage": False,
                    "include_proposals": False,
                    "directed_followups": False,
                },
                budget={"max_tasks": 100},
            ),
            source,
        )
        assert calls[:2] == [(local.id, 0), (other.id, 0)]
        assert (local.id, 1) in calls
        assert any(local.id in r.family_ids for r in package.results)
    finally:
        source.close()
